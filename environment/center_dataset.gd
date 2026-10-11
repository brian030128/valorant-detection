extends "res://dataset.gd"

# An off-axis-free central subfrustum preserves the native full-screen pixel scale.
const CROP_SIZE := 400
var rejection_attempt := 0

func center_frame(index: int, attempt: int) -> Array:
	rng.seed = 20261013 + index*104729 + attempt*15485863
	for actor in actors: actor.visible = false
	camera.position = Vector3(rng.randf_range(-2,2),rng.randf_range(1.35,1.85),rng.randf_range(3,7))
	camera.rotation_degrees = Vector3(rng.randf_range(-5,4),rng.randf_range(-13,13),0)
	# Exactly 85% enemy, 10% teammate, 5% empty, balanced within scene groups.
	if index%20 == 0: return []
	var k: int = index%actors.size()
	var actor: Node3D = actors[k]
	actor.visible = true
	actor.position = Vector3(rng.randf_range(-3,3),0,rng.randf_range(-24,1))
	actor.rotation.y = rng.randf_range(-PI,PI)
	actor.scale = Vector3.ONE*rng.randf_range(.94,1.06)
	var role := "teammate" if index%20 in [1,2] else "enemy"
	actor.set_meta("role",role)
	var record: Dictionary = actor_records[k].duplicate()
	record.merge({"role":role,"position":[actor.position.x,actor.position.y,actor.position.z],"yaw":actor.rotation.y,"scale":actor.scale.x},true)
	for player: AnimationPlayer in walk(actor,"AnimationPlayer"):
		var choices: Array = record["allowed_animations"]
		var animation: String = choices[rng.randi_range(0,choices.size()-1)]
		var time_: float = rng.randf()*player.get_animation(animation).length
		player.play(animation)
		player.seek(time_,true)
		player.advance(0)
		record["animation"] = animation
		record["animation_time"] = time_
	for skeleton: Skeleton3D in walk(actor,"Skeleton3D"):
		var head_index := skeleton.find_bone("Head")
		if head_index >= 0:
			head_transforms[k] = (skeleton.global_transform*skeleton.get_bone_global_pose(head_index)).affine_inverse()
			break
	var head_world: Vector3 = head_transforms[k].affine_inverse().origin
	var aim: Vector3 = head_world.lerp(actor.position+Vector3(0,1,0),rng.randf_range(0,.7))
	camera.look_at(aim,Vector3.UP)
	# Move target around the ROI, including edge truncation and partial cover.
	camera.rotate_object_local(Vector3.UP,rng.randf_range(-.15,.15))
	camera.rotate_object_local(Vector3.RIGHT,rng.randf_range(-.12,.12))
	for item in actor_surfaces:
		item["mask"].set_shader_parameter("head_world_to_local",head_transforms[item["actor"]])
		var mat: Material = item["beauty"]
		if mat is ShaderMaterial:
			mat.set_shader_parameter("rim_color",PURPLE if role=="enemy" else ALLY)
			mat.set_shader_parameter("rim_strength",2.2 if role=="enemy" else .99)
			mat.set_shader_parameter("rim_power",2.5)
			mat.set_shader_parameter("upper_bias",.6)
	return [record]

func generate() -> void:
	base_seed = 20261013
	viewport.size = Vector2i(CROP_SIZE,CROP_SIZE)
	camera.fov = rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*float(CROP_SIZE)/1080.0))
	for index in range(first,first+total):
		var group: int = index/per_group
		var split := split_for(group)
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
			mask_mode(true)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			var mask_image := viewport.get_texture().get_image()
			var pixels := mask_image.get_data()
			var stride: int = pixels.size()/(CROP_SIZE*CROP_SIZE)
			var body_pixels := 0
			var head_pixels := 0
			for offset in range(0,pixels.size(),stride):
				if pixels[offset]>15: body_pixels += 1
				if pixels[offset+1]>127: head_pixels += 1
			# Reject empty/imperceptible positives. Retain some genuinely head-hidden cases.
			if not records.is_empty() and (body_pixels<200 or (index%5!=0 and head_pixels<16)): continue
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
			var meta := {"index":index,"split":split,"scene_group":group,"scene_family":FAMILIES[(group+group/10)%8],"scene_seed":base_seed+group*7919,"frame_seed":base_seed+index*104729+attempt*15485863,"actors":records,"resolution":[400,400],"vertical_fov":camera.fov,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"camera_rotation_degrees":[camera.rotation_degrees.x,camera.rotation_degrees.y,camera.rotation_degrees.z],"purple_srgb":"#b04dbe","generator_version":"synthetic-center400-v1","acceptance_attempt":attempt,"visible_body_pixels":body_pixels,"visible_head_pixels":head_pixels}
			meta["crop"]={"source_resolution":[1920,1080],"xyxy":[760,340,1160,740],"source_vertical_fov":70.53,"method":"Equivalent central perspective subfrustum, no resizing or upscaling"}
			meta["sampling"]={"enemy_fraction":.85,"teammate_fraction":.10,"empty_fraction":.05,"minimum_body_pixels":200,"minimum_head_pixels_when_required":16,"head_required":index%5!=0}
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
