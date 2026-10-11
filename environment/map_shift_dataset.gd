extends "res://center_dataset.gd"

const NEW_MAPS = ["cargo_yard", "stone_plaza", "transit_tunnel", "neon_industrial"]
var active_map := 0

func build_scene(group: int) -> void:
	# Reconstruct original lighting first; change geometry and palette only.
	super.build_scene(group)
	for m in scenery: m.free()
	scenery.clear()
	for label in labels_3d: label.free()
	labels_3d.clear()
	rng.seed = 734921 + group*7919 + active_map*100003
	var floor_colors = [Color("48555c"),Color("a59a82"),Color("555f6b"),Color("303849")]
	block(Vector3(0,-.2,-14),Vector3(50,.4,65),floor_colors[active_map])
	if active_map == 0:
		var colors = [Color("b54f30"),Color("377b93"),Color("d3a738"),Color("73864d")]
		for side in [-1,1]:
			for bay in 8:
				var z := 5.0-bay*5.0
				var x: float = side*rng.randf_range(5.0,7.0)
				var col: Color = colors[rng.randi_range(0,3)]
				block(Vector3(x,1.4,z),Vector3(2.7,2.8,4.6),col)
				for stripe in 9:
					block(Vector3(x-side*1.38,1.4,z-2+stripe*.5),Vector3(.07,2.65,.07),col.darkened(.22))
				if bay%2==0: block(Vector3(x,4.25,z),Vector3(2.7,2.8,4.6),colors[(bay+1)%4])
		for z in [-5,-19,-31]:
			block(Vector3(-7,4,z),Vector3(.4,8,.4),Color("e9a72b"))
			block(Vector3(7,4,z),Vector3(.4,8,.4),Color("e9a72b"))
			block(Vector3(0,8,z),Vector3(14,.45,.45),Color("e9a72b"))
		block(Vector3(0,2,-34),Vector3(18,4,.3),Color("536a7b"))
	elif active_map == 1:
		var stone := Color("c8b99a")
		for side in [-1,1]:
			for bay in 7:
				var z := 5.0-bay*6
				cylinder(Vector3(side*5.5,2.2,z),.55,4.4,stone)
				block(Vector3(side*5.5,4.6,z),Vector3(1.7,.45,1.7),stone.lightened(.12))
				block(Vector3(side*7,2,z),Vector3(.8,4,5),stone.darkened(.16))
				for row in 5:
					block(Vector3(side*6.55,.5+row*.7,z),Vector3(.06,.025,4.8),stone.darkened(.38))
		for k in 20:
			var x: float = (-1 if k%2==0 else 1)*rng.randf_range(4,7)
			var rock := block(Vector3(x,.35,rng.randf_range(-30,2)),Vector3(rng.randf_range(.4,1.3),.7,.9),stone.darkened(.25))
			rock.rotation.y = rng.randf_range(-PI,PI)
		for row in 6:
			block(Vector3(0,.5+row*.85,-34),Vector3(17,.8,1.2),stone.lightened(row*.02))
	elif active_map == 2:
		for side in [-1,1]:
			block(Vector3(side*5.4,2.7,-13),Vector3(.5,5.4,44),Color("8a9da7"))
			for bay in 12:
				var z := 5.0-bay*3.4
				block(Vector3(side*5.05,2.1,z),Vector3(.12,1.8,2.1),Color("174c67"))
				block(Vector3(side*4.8,.5,z),Vector3(.8,1,1.8),Color("cba04e"))
			block(Vector3(side*3.8,.02,-13),Vector3(.2,.025,44),Color("e9c454"))
		block(Vector3(0,5.5,-13),Vector3(11,.3,44),Color("3b4c63"))
		for bay in 10:
			var z := 4.0-bay*4
			block(Vector3(0,4.9,z),Vector3(10.5,.35,.5),Color("42667a"))
			block(Vector3(0,4.65,z),Vector3(3,.08,.18),Color("e4e4c4"))
		block(Vector3(0,2.5,-35),Vector3(11,5,.6),Color("234657"))
	else:
		for side in [-1,1]:
			block(Vector3(side*6,3,-13),Vector3(.6,6,44),Color("353b57"))
			for bay in 10:
				var z := 5.0-bay*4
				var color := Color("a748ad") if bay%2==0 else Color("28a1b0")
				block(Vector3(side*5.65,2.6,z),Vector3(.1,3.8,.14),color)
				var panel := block(Vector3(side*5.25,1.5,z),Vector3(.9,3,2.5),Color("465879"))
				panel.rotation.y = side*.18
				block(Vector3(side*4.74,2.2,z),Vector3(.08,.65,1.4),color)
		for k in 9:
			var beam := block(Vector3(0,5.8,4-k*4.5),Vector3(12,.24,.35),Color("89769b"))
			beam.rotation.z = .10 if k%2==0 else -.10
		block(Vector3(0,3,-34),Vector3(12,6,.5),Color("505076"))
		for k in 9:
			block(Vector3(-5+k*1.25,3,-33.7),Vector3(.14,5.5,.08),Color("ba57b7") if k%2 else Color("4cc1c8"))
	# Different side cover, with occasional foreground occlusion kept in the test.
	for k in 5:
		var x: float = (-1 if k%2==0 else 1)*rng.randf_range(2.8,4.2)
		var h := rng.randf_range(.6,1.7)
		block(Vector3(x,h/2,rng.randf_range(-26,-3)),Vector3(rng.randf_range(.5,1.2),h,1),floor_colors[active_map].lightened(.15))
	for k in 24:
		block(Vector3(0,.015,6-k*1.6),Vector3(11,.015,.025),floor_colors[active_map].darkened(.28))

func replay(meta: Dictionary) -> void:
	for actor in actors: actor.visible = false
	var p: Array = meta["camera_position"]
	var r: Array = meta["camera_rotation_degrees"]
	camera.position = Vector3(p[0],p[1],p[2])
	camera.rotation_degrees = Vector3(r[0],r[1],r[2])
	for record in meta["actors"]:
		var k: int = int(record["instance_id"])-1
		var actor: Node3D = actors[k]
		assert(actor_records[k]["character"]==record["character"])
		actor.visible = true
		p = record["position"]
		actor.position = Vector3(p[0],p[1],p[2])
		actor.rotation.y = record["yaw"]
		actor.scale = Vector3.ONE*record["scale"]
		actor.set_meta("role",record["role"])
		for player: AnimationPlayer in walk(actor,"AnimationPlayer"):
			player.play(record["animation"])
			player.seek(record["animation_time"],true)
			player.advance(0)
		for skeleton: Skeleton3D in walk(actor,"Skeleton3D"):
			var head_index := skeleton.find_bone("Head")
			if head_index>=0:
				head_transforms[k]=(skeleton.global_transform*skeleton.get_bone_global_pose(head_index)).affine_inverse()
				break
	for item in actor_surfaces:
		item["mask"].set_shader_parameter("head_world_to_local",head_transforms[item["actor"]])
		var mat: Material = item["beauty"]
		if mat is ShaderMaterial:
			var role: String = actors[item["actor"]].get_meta("role","enemy")
			mat.set_shader_parameter("rim_color",PURPLE if role=="enemy" else ALLY)
			mat.set_shader_parameter("rim_strength",2.2 if role=="enemy" else .99)
			mat.set_shader_parameter("rim_power",2.5)
			mat.set_shader_parameter("upper_bias",.6)

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
			var new_index: int = map_index*10000+original_index
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
			meta["scene_group"]=map_index*10000+group
			meta["index"]=new_index
			meta["scene_family"]=NEW_MAPS[map_index]
			meta["generator_version"]="paired-map-shift-v1"
			meta["map_seed"]=734921+group*7919+map_index*100003
			meta["experiment"]="Original test camera, pose, scale, role, animation and lighting replayed; novel geometry/palette; no target relocation or visibility rejection"
			for key in ["sampling","visible_body_pixels","visible_head_pixels","acceptance_attempt"]:meta.erase(key)
			FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
			if (i+1)%50==0:print("MAP_PROGRESS ",NEW_MAPS[map_index]," ",i+1,"/",limit)
	print("MAP_SHIFT_COMPLETE images=",4*limit)
