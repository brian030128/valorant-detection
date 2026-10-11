extends "res://map_shift_dataset.gd"
const TEXTURE_MAPS = ["textured_atrium","ceramic_passage","weathered_service_yard","painted_arcade"]
const SURFACE_SHADER = preload("res://surface_patterns.gdshader")

func build_scene(group: int) -> void:
	super.build_scene(group)
	for m in scenery: m.free()
	scenery.clear()
	for label in labels_3d: label.free()
	labels_3d.clear()
	rng.seed = 427119+group*104729+active_map*1000003
	var colors = [Color("a89c86"),Color("6b9996"),Color("838a8b"),Color("b39f91")]
	var c: Color = colors[active_map]
	block(Vector3(0,-.2,-12),Vector3(65,.4,100),c)
	for side in [-1,1]:
		for bay in 9:
			var z := 12.0-bay*6.2
			var x: float = side*rng.randf_range(4.8,7.2)
			if active_map==0:
				cylinder(Vector3(x,3,z),.5,6,c.lightened(.2))
				block(Vector3(x,5.8,z),Vector3(2,.5,5.8),c.darkened(.15))
				block(Vector3(x+side*1.2,2.2,z),Vector3(.4,4.4,5.8),c)
				block(Vector3(x-side*.7,.5,z+1),Vector3(1.8,1,2),Color("8e7055"))
			elif active_map==1:
				block(Vector3(x,2.7,z),Vector3(.5,5.4,6.1),c)
				block(Vector3(x-side*.4,.9,z),Vector3(.6,1.8,5.8),c.lightened(.3))
				block(Vector3(x-side*.7,3.3,z),Vector3(.6,1.6,1.5),Color("b8c2c1"))
				block(Vector3(0,5.4,z),Vector3(15,.3,.4),Color("959b9c"))
			elif active_map==2:
				block(Vector3(x,1.5,z),Vector3(2.7,3,3.4),c)
				for k in 3:
					var pipe := cylinder(Vector3(x-side*1.5,.7+k*.7,z),.18,5.8,Color("798386"))
					pipe.rotation.x=PI/2
				block(Vector3(x,4,z),Vector3(3,.25,4),Color("b19b64"))
			else:
				block(Vector3(x,2.5,z),Vector3(1.3,5,6),c)
				block(Vector3(x-side*.8,3.2,z),Vector3(.25,2.2,4.5),c.lightened(.15))
				var awning := block(Vector3(x-side*1.1,3.7,z),Vector3(2,.15,4.8),Color("859ab0"))
				awning.rotation.z=side*.18
				block(Vector3(x-side*.9,.45,z),Vector3(1.7,.9,2.3),Color("997759"))
	if active_map==1:block(Vector3(0,5.6,-12),Vector3(16,.3,67),c.darkened(.25))
	for k in 8:
		var h := rng.randf_range(.5,1.7)
		var x: float = (-1 if k%2==0 else 1)*rng.randf_range(3,4.4)
		block(Vector3(x,h/2,rng.randf_range(-32,5)),Vector3(.9,h,1.1),c.darkened(.15))
	block(Vector3(0,3,-45),Vector3(22,6,.4),c)
	for i in scenery.size():
		var m: MeshInstance3D = scenery[i]
		var old: StandardMaterial3D = m.get_meta("beauty")
		var material := ShaderMaterial.new()
		material.shader=SURFACE_SHADER
		material.set_shader_parameter("base_color",old.albedo_color)
		var patterns = [[7,1,3,0],[2,2,7,0],[4,0,5,4],[6,1,3,6]]
		material.set_shader_parameter("pattern",patterns[active_map][i%4])
		material.set_shader_parameter("scale_m",rng.randf_range(.65,1.5))
		material.set_shader_parameter("texture_amount",0.0 if "--flat" in OS.get_cmdline_user_args() else 1.0)
		m.set_meta("beauty",material)
		m.material_override=material

func generate() -> void:
	base_seed = 20261013
	viewport.size = Vector2i(400,400)
	camera.fov = rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*400.0/1080.0))
	var source := ProjectSettings.globalize_path("res://../datasets/valorant_center400_10k/metadata/test")
	var files := DirAccess.get_files_at(source)
	files.sort()
	var limit := mini(total,files.size())
	for map_index in 4:
		active_map = map_index
		scene_group = -1
		for i in limit:
			var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(source.path_join(files[i])))
			var original_index: int = meta["index"]
			var group: int = meta["scene_group"]
			var new_index: int = 700000+map_index*10000+original_index
			var basename := "%06d"%new_index
			var meta_path := output_dir.path_join("metadata/test/"+basename+".json")
			if FileAccess.file_exists(meta_path) and not overwrite: continue
			if scene_group!=group:
				scene_group=group
				build_scene(group)
				load_pack(group)
			replay(meta)
			mask_mode(false)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			viewport.get_texture().get_image().save_jpg(output_dir.path_join("images/test/"+basename+".jpg"),.97)
			mask_mode(true)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			viewport.get_texture().get_image().save_png(output_dir.path_join("masks/test/"+basename+".png"))
			meta["source_index"]=original_index
			meta["source_scene_group"]=group
			meta["scene_group"]=700000+map_index*10000+group
			meta["index"]=new_index
			meta["scene_family"]=TEXTURE_MAPS[map_index]
			meta["generator_version"]="paired-textures-v1"
			meta["map_seed"]=427119+group*104729+map_index*1000003
			meta["texture_condition"]="flat" if "--flat" in OS.get_cmdline_user_args() else "textured"
			meta["texture_patterns"]=["concrete","brick","tile","wood","rust","hazard","graffiti","mosaic"]
			meta["experiment"]="Original test camera, pose, scale, role, animation and lighting replayed; novel geometry/palette; no target relocation or visibility rejection"
			for key in ["sampling","visible_body_pixels","visible_head_pixels","acceptance_attempt"]:meta.erase(key)
			FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
			if (i+1)%50==0:print("MAP_PROGRESS ",TEXTURE_MAPS[map_index]," ",i+1,"/",limit)
	print("MAP_SHIFT_COMPLETE images=",4*limit)
