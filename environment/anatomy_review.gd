extends "res://center_dataset.gd"

func generate() -> void:
	assert(anatomy_labels)
	viewport.size=Vector2i(400,400)
	camera.fov=38
	for character in catalog.size():
		load_pack((character*22)%29)
		for angle_index in 3:
			var records:=center_frame(4,0)
			var actor: Node3D=actors[0]
			var local_head: Transform3D=actor.global_transform.affine_inverse()*head_transforms[0].affine_inverse()
			actor.position=Vector3.ZERO
			actor.rotation=Vector3.ZERO
			actor.scale=Vector3.ONE
			head_transforms[0]=(actor.global_transform*local_head).affine_inverse()
			for item in actor_surfaces:item["mask"].set_shader_parameter("head_world_to_local",head_transforms[item["actor"]])
			var angle: float=[0.0,PI/2,PI][angle_index]
			var aim: Vector3=head_transforms[0].affine_inverse().origin
			for skeleton: Skeleton3D in walk(actor,"Skeleton3D"):
				var pelvis:=skeleton.find_bone("Pelvis")
				if pelvis>=0:aim=aim.lerp((skeleton.global_transform*skeleton.get_bone_global_pose(pelvis)).origin,.5)
			camera.position=aim+Vector3(sin(angle)*2.6,.05,cos(angle)*2.6)
			camera.look_at(aim)
			var record: Dictionary=records[0]
			record["role"]="enemy"
			var index:=character*3+angle_index
			mask_mode(true)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			viewport.get_texture().get_image().save_png(output_dir.path_join("masks/test/"+str(index)+".png"))
			mask_mode(false)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			viewport.get_texture().get_image().save_jpg(output_dir.path_join("images/test/"+str(index)+".jpg"),.97)
			var meta: Dictionary={"index":index,"scene_group":character,"scene_family":"anatomy_review","actors":records,"label_policy":"enemy-anatomy-v1","angle":angle_index}
			FileAccess.open(output_dir.path_join("metadata/test/"+str(index)+".json"),FileAccess.WRITE).store_string(JSON.stringify(meta))
		print("ANATOMY_REVIEW_CHARACTER ",catalog[character]["slug"])
	print("ANATOMY_REVIEW_COMPLETE")
