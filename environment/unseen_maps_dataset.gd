extends "res://map_shift_dataset.gd"

const CHALLENGE_MAPS = ["greenhouse", "power_substation", "museum_gallery", "construction_site"]

func build_scene(group: int) -> void:
	super.build_scene(group)
	for item in scenery: item.free()
	scenery.clear()
	for label in labels_3d: label.free()
	labels_3d.clear()
	rng.seed = 918734+group*104729+active_map*1000003
	var floors = [Color("7b8266"),Color("78818a"),Color("a09b95"),Color("958675")]
	block(Vector3(0,-.2,-12),Vector3(60,.4,90),floors[active_map])
	if active_map==0:
		# Open glazing bays: solid frame geometry and opaque foliage, no transparent mask ambiguity.
		for side in [-1,1]:
			for bay in 9:
				var z := 9.0-bay*5
				block(Vector3(side*6,2.8,z),Vector3(.15,5.6,.15),Color("c2cfbf"))
				block(Vector3(side*4.7,.5,z),Vector3(1.7,1,3.2),Color("77634d"))
				for k in 4:
					var x: float = side*rng.randf_range(4.1,5.3)
					var height := rng.randf_range(1.2,2.8)
					cylinder(Vector3(x,height/2+.7,z-1+k*.6),.07,height,Color("53693d"))
					var leaf := block(Vector3(x,height+.4,z-1+k*.6),Vector3(.8,.55,.7),Color("507740").lightened(rng.randf_range(0,.2)))
					leaf.rotation.z = rng.randf_range(-.7,.7)
				block(Vector3(side*6,2.1,z),Vector3(.12,.12,5),Color("c2cfbf"))
		for bay in 9:
			block(Vector3(0,5.6,9-bay*5),Vector3(12,.14,.14),Color("b6c9b7"))
			for side in [-1,1]:
				var roof := block(Vector3(side*3,6.5,9-bay*5),Vector3(6.4,.12,.12),Color("b6c9b7"))
				roof.rotation.z = -side*.3
	elif active_map==1:
		for side in [-1,1]:
			for bay in 8:
				var z := 9.0-bay*5.5
				var x: float = side*rng.randf_range(4.7,6)
				block(Vector3(x,1.2,z),Vector3(2.5,2.4,3.2),Color("788f88"))
				for k in 6:
					block(Vector3(x-side*1.28,1.2,z-1.3+k*.5),Vector3(.12,2.1,.12),Color("b0b8ae"))
				for k in 3:
					cylinder(Vector3(x-.7+k*.7,2.9,z),.17,1,Color("967451"))
				block(Vector3(side*8,3,z),Vector3(.25,6,.25),Color("535f6c"))
				block(Vector3(side*8,5.4,z),Vector3(.1,.1,5.5),Color("31363e"))
				block(Vector3(side*3.8,.03,z),Vector3(.16,.035,4.6),Color("d8bc43"))
		for z in [-4,-21,-36]:
			block(Vector3(0,6.3,z),Vector3(17,.25,.25),Color("777e83"))
			for x in [-3,0,3]:cylinder(Vector3(x,5.8,z),.14,.8,Color("a79777"))
	elif active_map==2:
		block(Vector3(0,6,-12),Vector3(18,.3,60),Color("c8c6bc"))
		for side in [-1,1]:
			block(Vector3(side*7.5,3,-12),Vector3(.4,6,60),Color("d4cbbc"))
			for bay in 8:
				var z := 8.0-bay*5.8
				block(Vector3(side*7.2,2.7,z),Vector3(.2,2.8,3.4),Color("554139"))
				block(Vector3(side*7.06,2.7,z),Vector3(.1,2.45,3.05),Color.from_hsv(rng.randf(),.35,.65))
				for k in 5:
					block(Vector3(side*6.99,1.7+k*.45,z+rng.randf_range(-1,1)),Vector3(.04,.2,.8),Color.from_hsv(rng.randf(),.5,.8))
				cylinder(Vector3(side*4.8,.65,z),.65,1.3,Color("8a8478"))
				var sculpture := block(Vector3(side*4.8,1.9,z),Vector3(.8,1.2,.8),Color("b2ae9e"))
				sculpture.rotation = Vector3(.2,rng.randf_range(-PI,PI),.35)
				if bay%3==0:block(Vector3(side*3.8,1.6,z+2.5),Vector3(2.2,3.2,.3),Color("bdb5a8"))
		for bay in 10:
			block(Vector3(0,5.7,10-bay*5),Vector3(2.5,.1,.6),Color("e3dfca"))
	else:
		for side in [-1,1]:
			for bay in 9:
				var z := 9.0-bay*5.5
				block(Vector3(side*6.5,2,z),Vector3(3,4,4.8),Color("92968f"))
				for level in 3:
					block(Vector3(side*4.7,.5+level*2,z),Vector3(1.4,.15,5.4),Color("9e7b51"))
					for offset in [-2,2]:
						cylinder(Vector3(side*4.1,2.5,z+offset),.065,5,Color("bdaf81"))
					var brace := block(Vector3(side*4.15,1.5+level,z),Vector3(.08,.08,4.7),Color("7c8586"))
					brace.rotation.x = .5 if bay%2 else -.5
				if bay%2==0:
					block(Vector3(side*3.5,.45,z),Vector3(1.4,.9,2.4),Color("b48d59"))
					for stripe in 5:block(Vector3(side*3.5,.92,z-.8+stripe*.4),Vector3(1.4,.08,.1),Color("d1b482"))
		block(Vector3(-8,7,-23),Vector3(.6,14,.6),Color("d2b24d"))
		block(Vector3(0,13,-23),Vector3(22,.5,.5),Color("d2b24d"))
	# Seeded side props can create genuine visibility changes; evaluation measures them.
	for k in 5:
		var h := rng.randf_range(.5,1.4)
		var x: float = (-1 if k%2==0 else 1)*rng.randf_range(2.8,4)
		block(Vector3(x,h/2,rng.randf_range(-29,3)),Vector3(.7,h,.8),floors[active_map].lightened(.12))
	block(Vector3(0,2,-40),Vector3(20,4,.4),floors[active_map].darkened(.12))

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
			var new_index: int = 400000+map_index*10000+original_index
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
			meta["scene_group"]=400000+map_index*10000+group
			meta["index"]=new_index
			meta["scene_family"]=CHALLENGE_MAPS[map_index]
			meta["generator_version"]="unseen-families-v1"
			meta["map_seed"]=918734+group*104729+map_index*1000003
			meta["experiment"]="Original test camera, pose, scale, role, animation and lighting replayed; novel geometry/palette; no target relocation or visibility rejection"
			for key in ["sampling","visible_body_pixels","visible_head_pixels","acceptance_attempt"]:meta.erase(key)
			FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
			if (i+1)%50==0:print("MAP_PROGRESS ",CHALLENGE_MAPS[map_index]," ",i+1,"/",limit)
	print("MAP_SHIFT_COMPLETE images=",4*limit)
