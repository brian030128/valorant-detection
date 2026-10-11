extends "res://map_shift_dataset.gd"

var target_cover: MeshInstance3D

func build_scene(group: int) -> void:
	target_cover = null
	active_map = group%4
	super.build_scene(group)

func center_frame(index: int, attempt: int) -> Array:
	if is_instance_valid(target_cover):
		scenery.erase(target_cover)
		target_cover.free()
		target_cover = null
	# Use independent frame seeds and a guaranteed positive base sample.
	var records := super.center_frame(index*20+3,attempt)
	if index%4==3:
		for actor in actors: actor.visible = false
		return []
	var record: Dictionary = records[0]
	var k: int = int(record["instance_id"])-1
	var actor: Node3D = actors[k]
	var head_world: Vector3 = head_transforms[k].affine_inverse().origin
	if index%4 in [0,1]:
		# Move the camera back while keeping native pixel density; no image resize.
		var distance := rng.randf_range(28,43) if index%4==0 else rng.randf_range(15,28)
		camera.position = actor.position+Vector3(rng.randf_range(-2,2),rng.randf_range(1.4,2.2),distance)
		camera.look_at(head_world.lerp(actor.position+Vector3.UP,.3),Vector3.UP)
		camera.rotate_object_local(Vector3.UP,rng.randf_range(-.08,.08))
		camera.rotate_object_local(Vector3.RIGHT,rng.randf_range(-.08,.08))
	else:
		# A narrow upright target_cover edge intersects the head and body silhouette.
		camera.look_at(head_world.lerp(actor.position+Vector3.UP,.3),Vector3.UP)
		var point := camera.position.lerp(head_world,.82)
		point += camera.global_basis.x*rng.randf_range(.08,.16)
		target_cover = block(point,Vector3(.22,3,.18),Color("657783"))
		target_cover.rotation.y = camera.rotation.y
	var role := "teammate" if (index/4)%4==0 else "enemy"
	record["role"] = role
	actor.set_meta("role",role)
	for item in actor_surfaces:
		var mat: Material = item["beauty"]
		if mat is ShaderMaterial:
			mat.set_shader_parameter("rim_color",PURPLE if role=="enemy" else ALLY)
			mat.set_shader_parameter("rim_strength",2.2 if role=="enemy" else .99)
	return records

func scene_name() -> String:
	return NEW_MAPS[active_map]

func generate() -> void:
	base_seed = 20261027
	viewport.size = Vector2i(CROP_SIZE,CROP_SIZE)
	camera.fov = rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*float(CROP_SIZE)/1080.0))
	for index in range(first,first+total):
		if "--negative-only" in OS.get_cmdline_user_args() and index%4!=3: continue
		var group: int = index/per_group
		var split := "train"
		var basename := "%06d"%index
		var meta_path := output_dir.path_join("metadata/"+split+"/"+basename+".json")
		if FileAccess.file_exists(meta_path) and not overwrite: continue
		if group != scene_group:
			scene_group = group
			build_scene(group)
			load_pack(group)
		var accepted := false
		for attempt in 120:
			var records := center_frame(index,attempt)
			var uncovered_head_pixels := 0
			if index%4==2:
				target_cover.visible = false
				mask_mode(true)
				await get_tree().process_frame
				RenderingServer.force_draw(false)
				var unmasked := viewport.get_texture().get_image().get_data()
				var unmasked_stride: int = unmasked.size()/(400*400)
				for offset in range(0,unmasked.size(),unmasked_stride):
					if unmasked[offset+1]>127: uncovered_head_pixels += 1
				target_cover.visible = true
			mask_mode(true)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			var mask_image := viewport.get_texture().get_image()
			var pixels := mask_image.get_data()
			var stride: int = pixels.size()/(CROP_SIZE*CROP_SIZE)
			var body_pixels := 0
			var head_pixels := 0
			var head_min := Vector2i(400,400)
			var head_max := Vector2i(-1,-1)
			for offset in range(0,pixels.size(),stride):
				if pixels[offset]>15: body_pixels += 1
				if pixels[offset+1]>127:
					head_pixels += 1
					var pos := Vector2i((offset/stride)%400,(offset/stride)/400)
					head_min = head_min.min(pos)
					head_max = head_max.max(pos)
			# Reject empty/imperceptible positives. Retain some genuinely head-hidden cases.
			if not records.is_empty() and (body_pixels<40 or head_pixels<3): continue
			var short_side := mini(head_max.x-head_min.x+1,head_max.y-head_min.y+1)
			if index%4 in [0,1] and (short_side<2 or short_side>=16): continue
			if index%4==0 and short_side>=8: continue
			if index%4==2 and (head_pixels>uncovered_head_pixels*.9 or head_pixels<uncovered_head_pixels*.15): continue
			mask_mode(false)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			var beauty := viewport.get_texture().get_image()
			assert(beauty.save_jpg(output_dir.path_join("images/"+split+"/"+basename+".jpg"),.97)==OK)
			assert(mask_image.save_png(output_dir.path_join("masks/"+split+"/"+basename+".png"))==OK)
			if "--save-context" in OS.get_cmdline_user_args() and index==first+3:
				viewport.size = Vector2i(1920,1080)
				camera.fov = 70.53
				await get_tree().process_frame
				RenderingServer.force_draw(false)
				viewport.get_texture().get_image().save_jpg(output_dir.path_join("context_full.jpg"),.97)
				mask_mode(true)
				await get_tree().process_frame
				RenderingServer.force_draw(false)
				viewport.get_texture().get_image().save_png(output_dir.path_join("context_full_mask.png"))
				viewport.size = Vector2i(CROP_SIZE,CROP_SIZE)
				camera.fov = rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*float(CROP_SIZE)/1080.0))
			var meta := {"index":index,"split":split,"scene_group":group,"scene_family":scene_name(),"scene_seed":base_seed+group*7919,"frame_seed":20261013+(index*20+3)*104729+attempt*15485863,"actors":records,"resolution":[400,400],"vertical_fov":camera.fov,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"camera_rotation_degrees":[camera.rotation_degrees.x,camera.rotation_degrees.y,camera.rotation_degrees.z],"purple_srgb":"#b04dbe","generator_version":"targeted-center400-v1","acceptance_attempt":attempt,"visible_body_pixels":body_pixels,"visible_head_pixels":head_pixels}
			meta["crop"]={"source_resolution":[1920,1080],"xyxy":[760,340,1160,740],"source_vertical_fov":70.53,"method":"Equivalent central perspective subfrustum, no resizing or upscaling"}
			meta["target_category"] = ["tiny_head","small_head","partial_cover","background_negative"][index%4]
			meta["head_short_side"] = short_side
			meta["uncovered_head_pixels"] = uncovered_head_pixels
			meta["scene_seed"] = 734921+group*7919+active_map*100003
			meta["enemy_highlight"]={"rim_strength":2.2,"rim_power":2.5,"upper_bias":.6,"outline_pixels":0,"outline_depth_bias_m":0}
			meta["placement"]={"minimum_player_distance_m":MIN_PLAYER_DISTANCE,"screen_envelope_gap_pixels":SCREEN_GAP_PIXELS,"policy":"One actor per crop; never stacked"}
			FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
			accepted = true
			break
		if not accepted:
			push_error("Could not place visible target at index "+str(index))
			get_tree().quit(1)
			return
		if (index+1)%10==0: print("PROGRESS ",index+1," elapsed_s=",(Time.get_ticks_msec()-start_time)/1000.0)
	print("GENERATION_COMPLETE count=",total," output=",output_dir)
