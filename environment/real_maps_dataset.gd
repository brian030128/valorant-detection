extends "res://center_dataset.gd"

var map_surfaces: Array = []
var map_name := "ascent"
var render_split := "train"
var teammate_negatives := false

func negative_mix_role(local_index: int) -> String:
	# Shuffle a balanced 20-frame block independently of pose/camera/HUD RNG.
	var sampler := RandomNumberGenerator.new()
	sampler.seed=9137+map_number*104729+(local_index/20)*15485863
	var roles: Array[String]=[]
	for i in 20:roles.append("background" if i<3 else "teammate" if i<8 else "enemy")
	for i in range(19,0,-1):
		var j:=sampler.randi_range(0,i)
		var temporary:=roles[i]
		roles[i]=roles[j]
		roles[j]=temporary
	return roles[local_index%20]
var map_number := 0
var map_data: Dictionary
var active_view := 0
var active_region := ""
var map_root: Node3D
# Keep both render targets allocated; changing MSAA on every pass can invalidate
# in-flight rendering resources. Only one viewport draws at a time.
var beauty_viewport: SubViewport
var beauty_camera: Camera3D

func vec(values: Array) -> Vector3:
	return Vector3(values[0],values[2],-values[1])

func playable_surface(candidate: Dictionary) -> bool:
	var name_: String=candidate["surface"].to_lower()
	for word in ["roof","ceiling","wall","building","glass","cliff","fence","railing"]:
		if name_.contains(word):return false
	for word in ["ground","floor","stairs","stair","steps","ramp","road","pavement","terrain","platform","bridge"]:
		if name_.contains(word):return true
	return false

func mask_mode(enabled: bool) -> void:
	viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS if enabled else SubViewport.UPDATE_DISABLED
	beauty_viewport.render_target_update_mode=SubViewport.UPDATE_DISABLED if enabled else SubViewport.UPDATE_ALWAYS
	if not enabled:
		beauty_camera.transform=camera.global_transform
		beauty_camera.fov=camera.fov
		beauty_camera.near=camera.near
		beauty_camera.far=camera.far
	super.mask_mode(enabled)
	for item in map_surfaces:
		item["mesh"].set_surface_override_material(item["surface"],item["mask"] if enabled else item["beauty"])

func setup_map() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg=="--teammate-negatives":teammate_negatives=true
		if arg.begins_with("--split="):render_split=arg.trim_prefix("--split=")
		if arg.begins_with("--map="):map_name=arg.trim_prefix("--map=")
		if arg.begins_with("--map-number="):map_number=int(arg.trim_prefix("--map-number="))
	assert(render_split in ["train","val","test"])
	var folder := ProjectSettings.globalize_path("res://../assets/generated/valorant_maps/"+map_name)
	map_data=JSON.parse_string(FileAccess.get_file_as_string(folder.path_join("viewpoints.json")))
	var valid_views: Array=[]
	var source_view := 0
	for view in map_data["views"]:
		view["source_view_id"]=source_view
		source_view+=1
		if not playable_surface(map_data["candidates"][int(view["candidate"])]):continue
		if anatomy_labels:
			var region: String=str(map_data["candidates"][int(view["candidate"])]["region"])
			var bucket: int=posmod(region.hash(),20)
			var region_split := "val" if bucket==0 else "test" if bucket==1 else "train"
			if region_split!=render_split:continue
		var targets: Array=[]
		for target in view["targets"]:
			if playable_surface(map_data["candidates"][int(target)]):targets.append(target)
		if targets.size()<3:continue
		view["targets"]=targets
		valid_views.append(view)
	if valid_views.is_empty():
		push_error("No playable camera viewpoints for "+map_name+" / "+render_split)
		get_tree().quit(1)
		return
	map_data["views"]=valid_views
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	assert(document.append_from_file(folder.path_join("map.glb"),state)==OK)
	map_root=document.generate_scene(state)
	stage.add_child(map_root)
	var masks := {}
	var mipmapped := {}
	var processed_materials := {}
	var material_configs := {}
	var conversion: Dictionary=JSON.parse_string(FileAccess.get_file_as_string(folder.path_join("conversion.json")))
	for item in conversion["materials"]:material_configs[item["material"]]=item
	for mesh: MeshInstance3D in walk(map_root,"MeshInstance3D"):
		for surface in mesh.mesh.get_surface_count():
			var material := mesh.mesh.surface_get_material(surface)
			if not material:material=StandardMaterial3D.new()
			if material is StandardMaterial3D and not processed_materials.has(material.get_instance_id()):
				processed_materials[material.get_instance_id()]=true
				material.texture_filter=BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
				if material_configs.has(material.resource_name):
					var config: Dictionary=material_configs[material.resource_name]
					material.vertex_color_use_as_albedo=config.get("use_vertex_color",false)
					if config.get("color_mult")==null:
						var tint: Array=config["tint"]
						material.albedo_color=Color(tint[0],tint[1],tint[2],1)
				var texture: Texture2D=material.albedo_texture
				if texture:
					var texture_id: int=texture.get_instance_id()
					if not mipmapped.has(texture_id):
						var texture_image:=texture.get_image()
						if not texture_image.has_mipmaps():texture_image.generate_mipmaps()
						mipmapped[texture_id]=ImageTexture.create_from_image(texture_image)
					material.albedo_texture=mipmapped[texture_id]
			if material is StandardMaterial3D and material.transparency!=BaseMaterial3D.TRANSPARENCY_DISABLED:
				material.transparency=BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
				material.alpha_scissor_threshold=.35
			var key: int=material.get_instance_id()
			if not masks.has(key):
				var mask: StandardMaterial3D = material.duplicate() if material is StandardMaterial3D else black.duplicate()
				mask.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED
				mask.albedo_color=Color.BLACK
				mask.emission_enabled=false
				masks[key]=mask
			map_surfaces.append({"mesh":mesh,"surface":surface,"beauty":material,"mask":masks[key]})
	camera.far=500
	print("REAL_MAP_LOADED ",map_name," surfaces=",map_surfaces.size()," views=",map_data["views"].size())

func place(index: int, local_index: int, attempt: int) -> Array:
	var records := super.center_frame(index*20+1+(local_index/10)%4,attempt)
	# A prime stride visits a wide spread of sampled map positions before repeating.
	active_view=(local_index*7919+attempt*101+map_number*37)%map_data["views"].size()
	var view: Dictionary=map_data["views"][active_view]
	if anatomy_labels:active_view=int(view["source_view_id"])
	var origin: Dictionary=map_data["candidates"][int(view["candidate"])]
	active_region=origin["region"]
	var target_id: int=view["targets"][rng.randi_range(0,view["targets"].size()-1)]
	var target: Dictionary=map_data["candidates"][target_id]
	camera.position=vec(origin["point"])+Vector3(0,rng.randf_range(1.35,2.05),0)
	var record: Dictionary=records[0]
	var k: int=int(record["instance_id"])-1
	var actor: Node3D=actors[k]
	var local_head: Transform3D=actor.global_transform.affine_inverse()*head_transforms[k].affine_inverse()
	actor.position=vec(target["point"])+Vector3(0,.025,0)
	actor.rotation.y=rng.randf_range(-PI,PI)
	head_transforms[k]=(actor.global_transform*local_head).affine_inverse()
	var head_world: Vector3=head_transforms[k].affine_inverse().origin
	var aim: Vector3=head_world.lerp(actor.position+Vector3.UP,rng.randf_range(0,.55))
	camera.look_at(aim,Vector3.UP)
	# Frequent centered aim teaches actual HUD/head overlap, plus broad off-center positions.
	var centered: bool=local_index%4==0
	camera.rotate_object_local(Vector3.UP,rng.randf_range(-.018,.018) if centered else rng.randf_range(-.16,.16))
	camera.rotate_object_local(Vector3.RIGHT,rng.randf_range(-.018,.018) if centered else rng.randf_range(-.12,.12))
	camera.rotation.z=rng.randf_range(-.025,.025)
	var role := "teammate" if local_index%5==1 else "enemy"
	if anatomy_labels:role="enemy"
	if teammate_negatives:role=negative_mix_role(local_index)
	var ally_strength := 0.99
	if teammate_negatives:
		# Include ordinary visible teammates, not only conspicuous cyan silhouettes.
		ally_strength=0.0 if rng.randf()<.5 else rng.randf_range(.35,1.15)
	record.merge({"role":role,"position":[actor.position.x,actor.position.y,actor.position.z],"yaw":actor.rotation.y,"scale":actor.scale.x},true)
	if teammate_negatives:
		record["highlight_style"]="purple" if role=="enemy" else "none" if ally_strength==0 else "cyan"
		record["highlight_strength"]=2.2 if role=="enemy" else ally_strength
	actor.set_meta("role",role)
	for item in actor_surfaces:
		item["mask"].set_shader_parameter("head_world_to_local",head_transforms[item["actor"]])
		var material: Material=item["beauty"]
		if material is ShaderMaterial:
			material.set_shader_parameter("rim_color",PURPLE if role=="enemy" else ALLY)
			material.set_shader_parameter("rim_strength",2.2 if role=="enemy" else ally_strength)
	# Daylight range plus ambient lighting for indoor regions; retain original map textures.
	sky_color=Color("9eb6c9").lerp(Color("d5c4b0"),rng.randf()*.45)
	environment_resource.ambient_light_color=Color.WHITE
	environment_resource.ambient_light_energy=rng.randf_range(.85,1.15)
	sun.rotation_degrees=Vector3(rng.randf_range(-72,-30),rng.randf_range(-180,180),0)
	sun.light_color=Color("ffe9d0").lerp(Color("d7e9ff"),rng.randf())
	sun.light_energy=rng.randf_range(.9,1.35)
	if (teammate_negatives and role=="background") or (not teammate_negatives and local_index%20 in [0,9,19]):
		for a in actors:a.visible=false
		return []
	return records

func hud(beauty: Image, mask: Image, local_index: int) -> Dictionary:
	var styles := ["none","dot","cross","open","outlined","large"]
	var style: String=styles[local_index%6]
	if style=="none":return {"style":style}
	var palette := [Color("00ff00"),Color.WHITE,Color("00ffff"),Color("b04dbe"),Color("ff4444"),Color("ffff00")]
	var color: Color=palette[rng.randi_range(0,5)]
	var thickness := rng.randi_range(1,3)
	var length := rng.randi_range(3,8) if style!="large" else rng.randi_range(9,13)
	var gap := rng.randi_range(2,5) if style in ["open","outlined","large"] else 0
	var rectangles: Array[Rect2i]=[]
	var low: int=200-thickness/2
	if style=="dot":
		rectangles.append(Rect2i(low,low,thickness,thickness))
	elif gap==0:
		rectangles.append(Rect2i(200-length,low,length*2+1,thickness))
		rectangles.append(Rect2i(low,200-length,thickness,length*2+1))
	else:
		rectangles.append(Rect2i(200-gap-length,low,length,thickness))
		rectangles.append(Rect2i(201+gap,low,length,thickness))
		rectangles.append(Rect2i(low,200-gap-length,thickness,length))
		rectangles.append(Rect2i(low,201+gap,thickness,length))
	if style=="outlined":
		for rect in rectangles:
			beauty.fill_rect(rect.grow(1),Color.BLACK)
			mask.fill_rect(rect.grow(1),Color.BLACK)
	for rect in rectangles:
		beauty.fill_rect(rect,color)
		mask.fill_rect(rect,Color.BLACK)
	return {"style":style,"color":color.to_html(false),"thickness":thickness,"arm_length":length,"gap":gap,"opaque":true}

func generate() -> void:
	viewport.size=Vector2i(400,400)
	camera.fov=rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*400.0/1080.0))
	setup_map()
	if not is_instance_valid(map_root):return
	beauty_viewport=SubViewport.new()
	beauty_viewport.size=viewport.size
	beauty_viewport.msaa_3d=Viewport.MSAA_4X
	beauty_viewport.world_3d=viewport.world_3d
	beauty_viewport.render_target_update_mode=SubViewport.UPDATE_DISABLED
	add_child(beauty_viewport)
	beauty_camera=Camera3D.new()
	beauty_viewport.add_child(beauty_camera)
	for local_index in range(first,first+total):
		var index: int=1000000+map_number*10000+local_index
		var basename := str(index)
		var meta_path:=output_dir.path_join("metadata/"+render_split+"/"+basename+".json")
		if FileAccess.file_exists(meta_path) and not overwrite:continue
		var group: int=index/50
		if scene_group!=group:
			scene_group=group
			load_pack(group)
		var accepted:=false
		for attempt in 150:
			var records:=place(index,local_index,attempt)
			mask_mode(true)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			var mask_image:=viewport.get_texture().get_image()
			var pixels:=mask_image.get_data()
			var stride: int=pixels.size()/160000
			var body:=0
			var head:=0
			for p in range(0,pixels.size(),stride):
				if pixels[p]>15:body+=1
				if pixels[p+1]>127:head+=1
			if not records.is_empty() and (body<80 or (local_index%7!=0 and head<3)):continue
			mask_mode(false)
			await get_tree().process_frame
			RenderingServer.force_draw(false)
			var beauty:=beauty_viewport.get_texture().get_image()
			var crosshair:=hud(beauty,mask_image,local_index)
			assert(beauty.save_jpg(output_dir.path_join("images/"+render_split+"/"+basename+".jpg"),.97)==OK)
			assert(mask_image.save_png(output_dir.path_join("masks/"+render_split+"/"+basename+".png"))==OK)
			var meta: Dictionary={"index":index,"split":"train","scene_group":1000000+map_number*10000+active_view,"scene_family":map_name,"map_viewpoint":active_view,"spatial_region":active_region,"actors":records,"resolution":[400,400],"vertical_fov":camera.fov,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"camera_rotation_degrees":[camera.rotation_degrees.x,camera.rotation_degrees.y,camera.rotation_degrees.z],"purple_srgb":"#b04dbe","generator_version":"real-maps-hud-v1","acceptance_attempt":attempt,"crosshair":crosshair,"pre_hud_body_pixels":body,"pre_hud_head_pixels":head,"sun_rotation_degrees":[sun.rotation_degrees.x,sun.rotation_degrees.y,sun.rotation_degrees.z],"sun_energy":sun.light_energy,"ambient_energy":environment_resource.ambient_light_energy,"placement":{"minimum_player_distance_m":2.8,"screen_envelope_gap_pixels":16.0,"policy":"One actor; real map ground and line-of-sight samples"}}
			meta["split"]=render_split
			if anatomy_labels:
				meta["label_policy"]="enemy-anatomy-v1"
				if teammate_negatives:meta["label_policy"]="enemy-anatomy-teammate-negatives-v2"
				meta["scene_group"]=map_number*1000000+active_view
				meta["mask_encoding"]="R=instance*32; G=visible hair-excluded head; B=visible torso; other surfaces retain depth"
			meta["crop"]={"source_resolution":[1920,1080],"xyxy":[760,340,1160,740],"method":"Native central perspective subfrustum; no rescaling"}
			meta["enemy_highlight"]={"rim_strength":2.2,"rim_power":2.5,"upper_bias":.6,"outline_pixels":0,"outline_depth_bias_m":0}
			meta["render_quality"]={"beauty_msaa":4,"mask_msaa":0,"textures":"Original packed resolution; anisotropic mipmapped filtering","vertex_colors":true,"normal_maps":true}
			meta["render_execution"]="persistent-separate-beauty-and-mask-targets-v2"
			FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
			accepted=true
			break
		if not accepted:
			push_error("No visible placement "+str(index));get_tree().quit(1);return
		if (local_index+1)%10==0:print("REAL_MAP_PROGRESS ",map_name," ",local_index+1,"/",first+total," elapsed_s=",(Time.get_ticks_msec()-start_time)/1000.0)
	print("REAL_MAP_COMPLETE ",map_name," count=",total)
