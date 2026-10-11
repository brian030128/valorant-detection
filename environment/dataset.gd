extends "res://main.gd"

# Separate entry point: the interactive render lab remains unchanged.
const FAMILIES = ["courtyard", "warehouse", "alley", "rooftop", "snow_depot", "desert", "garden", "laboratory"]
var rng := RandomNumberGenerator.new()
var output_dir: String
var total := 10000
var first := 0
var per_group := 50
var mask_shader: Shader
var environment_resource: Environment
var sun: DirectionalLight3D
var scenery: Array[MeshInstance3D] = []
var labels_3d: Array[Label3D] = []
var actor_surfaces: Array = []
var actor_records: Array = []
var head_transforms: Array[Transform3D] = []
var black: StandardMaterial3D
var scene_group := -1
var sky_color := Color("839bb0")
var start_time: int
var base_seed := 20261011
var overwrite := false
var anatomy_labels := false
const MIN_PLAYER_DISTANCE := 2.8
const SCREEN_GAP_PIXELS := 16.0

func spawn_screen_bounds(position_: Vector3) -> Rect2:
	# Conservative envelope around character-select poses and carried equipment.
	var bounds := Rect2()
	var initialized := false
	for x in [-1.3,1.3]:
		for y in [-.15,3.0]:
			for z in [-1.3,1.3]:
				var point := camera.unproject_position(position_ + Vector3(x,y,z))
				if not initialized:
					bounds = Rect2(point,Vector2.ZERO)
					initialized = true
				else: bounds = bounds.expand(point)
	return bounds

func _ready() -> void:
	Engine.max_fps = 0
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	source_root = ProjectSettings.globalize_path("res://../assets/source/kingdomarchives/")
	catalog = JSON.parse_string(FileAccess.get_file_as_string(source_root.path_join("catalog.json")))["characters"]
	output_dir = ProjectSettings.globalize_path("res://../datasets/valorant_synthetic_10k")
	for arg in OS.get_cmdline_user_args():
		if arg == "--anatomy": anatomy_labels = true
		if arg == "--overwrite": overwrite = true
		if arg.begins_with("--count="): total = int(arg.get_slice("=",1))
		if arg.begins_with("--start="): first = int(arg.get_slice("=",1))
		if arg.begins_with("--output="): output_dir = arg.trim_prefix("--output=")
		if arg.begins_with("--group-size="): per_group = int(arg.get_slice("=",1))
	shader = load("res://character.gdshader")
	mask_shader = load("res://instance_mask.gdshader")
	black = StandardMaterial3D.new()
	black.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	black.albedo_color = Color.BLACK
	viewport = SubViewport.new()
	viewport.size = Vector2i(1920,1080)
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.msaa_3d = Viewport.MSAA_DISABLED
	add_child(viewport)
	stage = Node3D.new()
	viewport.add_child(stage)
	camera = Camera3D.new()
	camera.fov = 70.53
	camera.near = .05
	camera.far = 200
	stage.add_child(camera)
	environment_resource = Environment.new()
	environment_resource.background_mode = Environment.BG_COLOR
	environment_resource.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment_resource.ambient_light_color = Color("c0d0de")
	environment_resource.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	var world := WorldEnvironment.new()
	world.environment = environment_resource
	stage.add_child(world)
	sun = DirectionalLight3D.new()
	sun.shadow_enabled = true
	stage.add_child(sun)
	for split in ["train","val","test"]:
		for folder in ["images","masks","metadata"]:
			DirAccess.make_dir_recursive_absolute(output_dir.path_join(folder).path_join(split))
	start_time = Time.get_ticks_msec()
	await generate()
	get_tree().quit()

func _process(_delta: float) -> void:
	pass

func _input(_event: InputEvent) -> void:
	pass

func split_for(group: int) -> String:
	# Ten consecutive groups span every scene family. Entire groups are held out.
	if group % 10 == 8: return "val"
	if group % 10 == 9: return "test"
	return "train"

func block(p: Vector3, size_: Vector3, color: Color) -> MeshInstance3D:
	var m := MeshInstance3D.new()
	var shape := BoxMesh.new()
	shape.size = size_
	m.mesh = shape
	m.position = p
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = rng.randf_range(.65,1)
	m.material_override = material
	m.set_meta("beauty",material)
	stage.add_child(m)
	scenery.append(m)
	return m

func cylinder(p: Vector3, radius: float, height: float, color: Color) -> MeshInstance3D:
	var m := block(p,Vector3.ONE,color)
	var shape := CylinderMesh.new()
	shape.top_radius = radius
	shape.bottom_radius = radius
	shape.height = height
	shape.radial_segments = 12
	m.mesh = shape
	return m

func foliage(p: Vector3, radius: float, color: Color) -> void:
	var m := block(p,Vector3.ONE,color)
	var shape := SphereMesh.new()
	shape.radius = radius
	shape.height = radius*1.6
	shape.radial_segments = 12
	shape.rings = 6
	m.mesh = shape

func build_scene(group: int) -> void:
	for m in scenery: m.free()
	scenery.clear()
	for s in labels_3d: s.free()
	labels_3d.clear()
	rng.seed = base_seed + group*7919
	# Rotate families independently of the split cycle, preventing family/split confounds.
	var family: int = (group + group/10) % FAMILIES.size()
	var wall_colors = [Color("c4ac95"),Color("717b83"),Color("aa8c85"),Color("a6acae"),Color("cedbe0"),Color("d9b787"),Color("acbbaa"),Color("cad2d4")]
	var floor_colors = [Color("8e8780"),Color("61666a"),Color("707078"),Color("737f82"),Color("d6e0e5"),Color("b59669"),Color("8b9a7b"),Color("777e87")]
	var wall: Color = wall_colors[family].darkened(rng.randf_range(0,.15))
	var floor_c: Color = floor_colors[family]
	var accent := Color.from_hsv(rng.randf(),rng.randf_range(.15,.5),rng.randf_range(.3,.65))
	var width := rng.randf_range(8,14) if family != 2 else rng.randf_range(4,7)
	sky_color = Color("9eb6c9") if family != 4 else Color("b5c7d4")
	environment_resource.background_color = sky_color
	environment_resource.ambient_light_energy = rng.randf_range(.28,.55)
	sun.rotation_degrees = Vector3(rng.randf_range(-70,-24),rng.randf_range(-75,75),0)
	sun.light_color = Color("ffe8c7").lerp(Color("d0e5ff"),rng.randf())
	sun.light_energy = rng.randf_range(.55,1.1)
	block(Vector3(0,-.2,-14),Vector3(60,.4,70),floor_c)
	# Modular facades, recessed panels, ledges, roofs and distant skyline.
	for side_sign in [-1,1]:
		for bay in 7:
			var z := 6.0-bay*6
			var height := rng.randf_range(4,9)
			block(Vector3(side_sign*width,height/2,z),Vector3(2,height,5.9),wall.lightened(rng.randf_range(-.12,.12)))
			block(Vector3(side_sign*(width-1.1),2.2,z),Vector3(.18,2.7,2.3),accent.darkened(.35))
			block(Vector3(side_sign*(width-1.2),3.8,z),Vector3(.4,.2,3.1),wall.lightened(.2))
			for pane in 3:
				block(Vector3(side_sign*(width-1.12),4.8,z-1.4+pane*1.4),Vector3(.12,1,1),Color("526e7d"))
			if family in [1,7]:
				block(Vector3(side_sign*(width-.3),5,z),Vector3(.5,.5,6),accent)
			if family in [0,5,6]:
				block(Vector3(side_sign*(width-1.7),3.5,z),Vector3(1.7,.15,3),accent)
	block(Vector3(0,3.5,-34),Vector3(width*2,7,1),wall)
	block(Vector3(rng.randf_range(-3,3),2,-33.4),Vector3(3,4,.15),accent.darkened(.4))
	if family in [1,7]:
		block(Vector3(0,7,-12),Vector3(width*2,.35,42),wall.darkened(.2))
		for z in [-4,-14,-24]:
			block(Vector3(0,6.5,z),Vector3(width*2,.3,.4),accent)
			block(Vector3(-2,6.25,z),Vector3(3,.08,.5),Color("e1e6d7"))
	if family == 3:
		for s in [-1,1]:
			block(Vector3(s*7,.6,-13),Vector3(.4,1.2,36),wall)
		for k in 15:
			block(Vector3(rng.randf_range(-35,35),rng.randf_range(3,7),-48-rng.randf_range(0,20)),Vector3(rng.randf_range(2,6),rng.randf_range(8,18),4),wall.darkened(.2))
	# Floor seams, lane paint, drainage and crosswalks.
	for k in 18:
		block(Vector3(0,.02,6-k*2.3),Vector3(width*2,.012,.018),floor_c.darkened(.18))
	for x in [-5.0,0.0,5.0]:
		block(Vector3(x,.02,-13),Vector3(.018,.012,40),floor_c.darkened(.22))
	for k in 7:
		block(Vector3(-width+2,.008,3-k*5),Vector3(.1,.012,2),Color("c6bc85"))
	for k in 14:
		var x := rng.randf_range(-width+2,width-2)
		var z := rng.randf_range(-31,-2)
		# Keep an open firing lane; edge objects and some interior cover remain.
		if abs(x)<1.4: x += 2.8
		var h := rng.randf_range(.5,2.2)
		var w := rng.randf_range(.6,2.2)
		var col := accent.lerp(wall,rng.randf())
		if k%3 == 0:
			cylinder(Vector3(x,h/2,z),w*.4,h,col)
		else:
			block(Vector3(x,h/2,z),Vector3(w,h,rng.randf_range(.6,2)),col)
			for stripe in [-1,1]:
				block(Vector3(x+stripe*w*.35,h/2,z+.51),Vector3(.06,h,.03),col.darkened(.35))
	if family in [0,6,5]:
		for k in 8:
			var p := Vector3((-1 if k%2 else 1)*(width-2),0,-k*4)
			block(p+Vector3(0,.35,0),Vector3(1.5,.7,1.5),wall.darkened(.2))
			cylinder(p+Vector3(0,1.2,0),.12,2,Color("6b5744"))
			foliage(p+Vector3(0,2.2,0),rng.randf_range(.6,1.2),Color("48664a").lightened(rng.randf_range(0,.15)))
	if family == 4:
		for k in 12:
			foliage(Vector3(rng.randf_range(-width,width),.05,rng.randf_range(-30,0)),rng.randf_range(.5,1.5),Color("e3ebed"))
	var signage := Label3D.new()
	signage.text = ["A / COURT","STORAGE 07","SECTOR B","ACCESS","DEPOT 04","SITE A","GARDEN","RESEARCH"][family]
	signage.position = Vector3(0,5,-33.3)
	signage.font_size = 96
	signage.pixel_size = .009
	signage.modulate = accent.darkened(.5)
	stage.add_child(signage)
	labels_3d.append(signage)

func load_pack(group: int) -> void:
	for actor in actors: actor.free()
	actors.clear()
	players.clear()
	materials.clear()
	actor_surfaces.clear()
	actor_records.clear()
	head_transforms.clear()
	textures.clear()
	for index in 4:
		var slug: String = catalog[(group*4+index)%catalog.size()]["slug"]
		var directory := source_root.path_join(slug)
		var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join("viewer_config.json")))
		var document := GLTFDocument.new()
		var state := GLTFState.new()
		var asset_folder := "anatomy_weighted" if anatomy_labels else "head_weighted"
		var err := document.append_from_file(ProjectSettings.globalize_path("res://../assets/generated/"+asset_folder+"/"+slug+".glb"),state)
		assert(err == OK)
		var actor: Node3D = document.generate_scene(state)
		stage.add_child(actor)
		actors.append(actor)
		head_transforms.append(Transform3D.IDENTITY)
		var material_info := {}
		for info in config["Materials"]: material_info[info["Name"]] = info
		var special_count := 0
		for mesh: MeshInstance3D in walk(actor,"MeshInstance3D"):
			for surface in mesh.mesh.get_surface_count():
				var original := mesh.mesh.surface_get_material(surface)
				var original_name: String = original.resource_name if original else ""
				var info: Dictionary = material_info.get(original_name,{}).duplicate(true)
				if original_name == config["Model"].get("SpecialMaterial", ""):
					if special_count == int(config["Model"].get("SpecialMaterialIndex",-1)) and info.has("DecalDF"):
						info["DF"] = info["DecalDF"]
						info["BaseUV2"] = true
						info["Type"] = "Decals"
					special_count += 1
				var beauty := make_material(info,directory,"enemy",0)
				mesh.set_surface_override_material(surface,beauty)
				var mask := ShaderMaterial.new()
				mask.shader = mask_shader
				mask.set_shader_parameter("anatomy_labels",anatomy_labels)
				mask.set_shader_parameter("instance_value",float((index+1)*32)/255.0)
				mask.set_shader_parameter("cutout",info.get("Type","")=="Decals")
				mask.set_shader_parameter("base_uv2",info.get("BaseUV2",false))
				if info.has("DF"):
					mask.set_shader_parameter("base_map",texture_for(directory.path_join("textures/"+str(info["DF"]).get_file())))
					mask.set_shader_parameter("has_base",true)
				actor_surfaces.append({"mesh":mesh,"surface":surface,"beauty":beauty,"mask":mask,"actor":index})
		var safe_animations: Array[String] = []
		for entry in config["Animations"]:
			if str(entry.get("Translatable","")).begins_with("Character Select Idle"):
				safe_animations.append(entry["Name"])
		# The public Yoru CS idle contains malformed stretched mask geometry.
		if slug == "yoru": safe_animations.assign(["Idle_No_Mask"])
		if safe_animations.is_empty(): safe_animations.append("Idle")
		actor_records.append({"character":slug,"instance_id":index+1,"allowed_animations":safe_animations})
		for player: AnimationPlayer in walk(actor,"AnimationPlayer"):
			player.speed_scale = 0
			players.append(player)
	print("GROUP ",group," ",FAMILIES[(group+group/10)%8]," ",actor_records)

func randomize_frame(index: int) -> Array:
	rng.seed = base_seed + index*104729
	var records: Array = []
	var occupied_positions: Array[Vector3] = []
	var occupied_bounds: Array[Rect2] = []
	var count := rng.randi_range(1,4)
	if index % 20 == 0: count = 0
	camera.position = Vector3(rng.randf_range(-2,2),rng.randf_range(1.35,1.85),rng.randf_range(3,7))
	camera.rotation_degrees = Vector3(rng.randf_range(-5,4),rng.randf_range(-13,13),rng.randf_range(-1,1))
	for k in actors.size():
		var actor := actors[k]
		actor.visible = k<count
		if not actor.visible: continue
		var placed := false
		for attempt in 120:
			var z := rng.randf_range(-25,1)
			if k==0 and index%3==0: z = rng.randf_range(-4,2)
			var spread := minf(7,(camera.position.z-z)*.52)
			var candidate := Vector3(rng.randf_range(-spread,spread),0,z)
			var projected := spawn_screen_bounds(candidate)
			var valid := true
			for previous in occupied_positions:
				if candidate.distance_to(previous) < MIN_PLAYER_DISTANCE: valid = false; break
			if valid:
				for previous in occupied_bounds:
					if projected.grow(SCREEN_GAP_PIXELS).intersects(previous): valid = false; break
			if valid:
				actor.position = candidate
				occupied_positions.append(candidate)
				occupied_bounds.append(projected)
				placed = true
				break
		if not placed:
			actor.visible = false
			continue
		actor.rotation.y = rng.randf_range(-PI,PI)
		actor.scale = Vector3.ONE * rng.randf_range(.94,1.06)
		var role := "enemy" if rng.randf()<.6 else "teammate"
		actor.set_meta("role",role)
		var record: Dictionary = actor_records[k].duplicate()
		record["role"] = role
		record["position"] = [actor.position.x,actor.position.y,actor.position.z]
		record["yaw"] = actor.rotation.y
		record["scale"] = actor.scale.x
		for player: AnimationPlayer in walk(actor,"AnimationPlayer"):
			var choices: Array = record["allowed_animations"]
			if not choices.is_empty():
				var animation: String = choices[rng.randi_range(0,choices.size()-1)]
				var time_ := rng.randf()*player.get_animation(animation).length
				player.play(animation)
				player.seek(time_,true)
				player.advance(0)
				record["animation"] = animation
				record["animation_time"] = time_
		records.append(record)
		for skeleton: Skeleton3D in walk(actor,"Skeleton3D"):
			var head_index := skeleton.find_bone("Head")
			if head_index >= 0:
				head_transforms[k] = (skeleton.global_transform * skeleton.get_bone_global_pose(head_index)).affine_inverse()
				break
	for item in actor_surfaces:
		item["mask"].set_shader_parameter("head_world_to_local",head_transforms[item["actor"]])
		var mat: Material = item["beauty"]
		if mat is ShaderMaterial:
			var role: String = actors[item["actor"]].get_meta("role","enemy")
			mat.set_shader_parameter("rim_color",PURPLE if role == "enemy" else ALLY)
			mat.set_shader_parameter("rim_strength",2.2 if role == "enemy" else .99)
			mat.set_shader_parameter("rim_power",2.5)
			mat.set_shader_parameter("upper_bias",.6)
	return records

func mask_mode(enabled: bool) -> void:
	for item in actor_surfaces:
		item["mesh"].set_surface_override_material(item["surface"],item["mask"] if enabled else item["beauty"])
	for mesh in scenery: mesh.material_override = black if enabled else mesh.get_meta("beauty")
	for label in labels_3d: label.visible = not enabled
	environment_resource.background_color = Color.BLACK if enabled else sky_color

func generate() -> void:
	for index in range(first,first+total):
		var group: int = index/per_group
		var split := split_for(group)
		var basename := "%06d" % index
		var meta_path := output_dir.path_join("metadata/"+split+"/"+basename+".json")
		if FileAccess.file_exists(meta_path) and not overwrite: continue
		if group != scene_group:
			scene_group = group
			build_scene(group)
			load_pack(group)
		var records := randomize_frame(index)
		mask_mode(false)
		await get_tree().process_frame
		# Explicit drawing keeps offscreen capture progressing when Windows occludes
		# the hidden renderer window and the normal window loop stops presenting.
		RenderingServer.force_draw(false)
		var image := viewport.get_texture().get_image()
		assert(image.save_jpg(output_dir.path_join("images/"+split+"/"+basename+".jpg"),.94)==OK)
		mask_mode(true)
		await get_tree().process_frame
		RenderingServer.force_draw(false)
		var mask_image := viewport.get_texture().get_image()
		assert(mask_image.save_png(output_dir.path_join("masks/"+split+"/"+basename+".png"))==OK)
		var meta := {"index":index,"split":split,"scene_group":group,"scene_family":FAMILIES[(group+group/10)%8],"scene_seed":base_seed+group*7919,"frame_seed":base_seed+index*104729,"actors":records,"resolution":[1920,1080],"vertical_fov":camera.fov,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"camera_rotation_degrees":[camera.rotation_degrees.x,camera.rotation_degrees.y,camera.rotation_degrees.z],"purple_srgb":"#b04dbe","head_definition":"visible surface with interpolated head/descendant skin weight >= 0.5","mask_encoding":"R=instance_id*32; G=255 for head, otherwise 0; background RGB=0"}
		meta["head_definition"] = "Head/descendant skin weights >= 0.5, clipped in rest and animated head-local space to exclude long hair/scarves; visible surface, not a game hitbox"
		meta["enemy_highlight"] = {"rim_strength":2.2,"rim_power":2.5,"upper_bias":.6,"outline_pixels":0,"outline_depth_bias_m":0}
		meta["mask_encoding"] = "R approximately instance_id*32 (round to nearest, <=3 quantization error); G=255 for visible head; background RGB=0"
		meta["generator_version"] = "synthetic-v3-spaced-players"
		meta["placement"] = {"minimum_player_distance_m":MIN_PLAYER_DISTANCE,"screen_envelope_gap_pixels":SCREEN_GAP_PIXELS,"failed_placements":"omit actor instead of forcing overlap"}
		FileAccess.open(meta_path,FileAccess.WRITE).store_string(JSON.stringify(meta))
		if (index+1)%10 == 0:
			print("PROGRESS ",index+1," elapsed_s=",(Time.get_ticks_msec()-start_time)/1000.0)
	print("GENERATION_COMPLETE count=",total," output=",output_dir)
