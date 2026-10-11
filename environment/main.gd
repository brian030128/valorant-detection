extends Control

const PURPLE := Color("b04dbe")
const ALLY := Color("75b8d0")
var source_root: String
var catalog: Array = []
var viewport: SubViewport
var viewport_container: SubViewportContainer
var stage: Node3D
var camera: Camera3D
var actors: Array[Node3D] = []
var players: Array[AnimationPlayer] = []
var materials: Array[ShaderMaterial] = []
var shader: Shader
var textures: Dictionary = {}
var character_select: OptionButton
var animation_select: OptionButton
var status: Label
var cover: MeshInstance3D
var side: VBoxContainer
var chosen := "viper"
var orbit_yaw := 0.0
var orbit_pitch := 0.03
var distance := 5.0
var target := Vector3(0, 1.05, 0)
var rotating := false
var spin := false
var playing := true
var rim_enabled := true
var rim_strength := 2.2
var rim_power := 2.5
var upper_bias := 0.6
var purple := PURPLE
var capture_busy := false
var selected_animation := ""
var startup_args: PackedStringArray

func _ready() -> void:
	source_root = ProjectSettings.globalize_path("res://../assets/source/kingdomarchives/")
	var parsed: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(source_root.path_join("catalog.json")))
	catalog = parsed["characters"]
	shader = load("res://character.gdshader")
	startup_args = OS.get_cmdline_user_args()
	for arg in startup_args:
		if arg.begins_with("--character="): chosen = arg.trim_prefix("--character=")
	build_ui()
	build_range()
	load_character(chosen)
	update_camera()
	if "--capture" in startup_args:
		await get_tree().create_timer(2.0).timeout
		await capture("preview_" + chosen)
		get_tree().quit()
	elif "--verify" in startup_args:
		await verify_scene()
		get_tree().quit()
	elif "--verify-all" in startup_args:
		var report: Array = []
		for entry in catalog:
			load_character(entry["slug"])
			await get_tree().create_timer(.15).timeout
			report.append({"character":chosen,"actors":actors.size(),"materials":materials.size(),"animations":animation_select.item_count})
		DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path("res://captures"))
		FileAccess.open("res://captures/all_characters_check.json",FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
		print("ALL_CHARACTERS_CHECKED ",report.size())
		get_tree().quit()

func label(text: String, size: int = 14, color := Color("bcc8d8")) -> Label:
	var item := Label.new()
	item.text = text
	item.clip_text = true
	item.add_theme_font_size_override("font_size", size)
	item.add_theme_color_override("font_color", color)
	side.add_child(item)
	return item

func section(text: String) -> void:
	var gap := Control.new()
	gap.custom_minimum_size.y = 12
	side.add_child(gap)
	label(text, 12, Color("818fa5"))

func button(text: String, action: Callable) -> Button:
	var item := Button.new()
	item.text = text
	item.custom_minimum_size.y = 34
	item.pressed.connect(action)
	side.add_child(item)
	return item

func slider(text: String, minimum: float, maximum: float, value: float, action: Callable) -> HSlider:
	var caption := label("%s  %.2f" % [text, value], 13)
	var item := HSlider.new()
	item.min_value = minimum
	item.max_value = maximum
	item.step = 0.01
	item.value = value
	item.value_changed.connect(func(v: float):
		caption.text = "%s  %.2f" % [text, v]
		action.call(v))
	side.add_child(item)
	return item

func build_ui() -> void:
	var background := ColorRect.new()
	background.color = Color("101722")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var panel := ScrollContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_LEFT_WIDE)
	panel.offset_right = 300
	panel.offset_left = 18
	panel.offset_top = 20
	panel.offset_bottom = -16
	panel.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(panel)
	side = VBoxContainer.new()
	side.custom_minimum_size.x = 264
	side.add_theme_constant_override("separation", 7)
	panel.add_child(side)
	label("RENDER / LAB", 24, Color("f0f4fb"))
	label("VALORANT CHARACTER STAGE", 11, Color("9e81c9"))
	section("CHARACTER")
	character_select = OptionButton.new()
	character_select.fit_to_longest_item = false
	character_select.clip_text = true
	character_select.custom_minimum_size.y = 34
	for entry in catalog:
		character_select.add_item(entry["name"])
		if entry["slug"] == chosen: character_select.select(character_select.item_count - 1)
	character_select.item_selected.connect(func(index: int): load_character(catalog[index]["slug"]))
	side.add_child(character_select)
	animation_select = OptionButton.new()
	animation_select.fit_to_longest_item = false
	animation_select.clip_text = true
	animation_select.custom_minimum_size.y = 34
	animation_select.item_selected.connect(func(index: int): set_animation(animation_select.get_item_text(index)))
	side.add_child(animation_select)
	button("Play / pause animation", func():
		playing = not playing
		for player in players: player.speed_scale = 1.0 if playing else 0.0)
	button("Turntable on / off", func(): spin = not spin)
	section("ENEMY  /  PURPLE")
	var picker := ColorPickerButton.new()
	picker.color = PURPLE
	picker.custom_minimum_size.y = 32
	picker.color_changed.connect(func(value: Color): purple = value; update_materials())
	side.add_child(picker)
	label("#B04DBE  ·  screenshot estimate", 12)
	slider("Rim intensity", 0, 3, rim_strength, func(v: float): rim_strength = v; update_materials())
	slider("Fresnel power", 0.5, 8, rim_power, func(v: float): rim_power = v; update_materials())
	slider("Upper-body bias", 0, 1, upper_bias, func(v: float): upper_bias = v; update_materials())
	button("Highlight on / off", func(): rim_enabled = not rim_enabled; update_materials())
	section("CAMERA & SCENE")
	slider("Camera distance (m)", 2.5, 18, distance, func(v: float): distance = v; update_camera())
	button("Reset camera", func(): orbit_yaw = 0; orbit_pitch = 0.03; distance = 5; target = Vector3(0,1.05,0); update_camera())
	button("Toggle foreground cover", func(): cover.visible = not cover.visible)
	button("Save PNG + metadata", func(): capture())
	section("NAVIGATION")
	label("Right-drag  /  orbit\nWheel  /  zoom\nW A S D  /  move target\nQ E  /  lower / raise\nF12  /  capture", 13)
	section("SCENE KEY")
	label("Purple  ·  enemy\nBlue  ·  teammate\nCover blocks highlights", 13)
	status = label("Loading character…", 12)
	status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status.custom_minimum_size.x = 250
	var container := SubViewportContainer.new()
	viewport_container = container
	container.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	container.offset_left = 318
	container.stretch = true
	add_child(container)
	viewport = SubViewport.new()
	viewport.size = Vector2i(1122,900)
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.msaa_3d = Viewport.MSAA_4X
	container.add_child(viewport)
	stage = Node3D.new()
	viewport.add_child(stage)
	camera = Camera3D.new()
	camera.fov = 70.53
	camera.near = 0.05
	camera.far = 150
	stage.add_child(camera)
	camera.current = true

func box(position: Vector3, dimensions: Vector3, color: Color) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = dimensions
	instance.mesh = mesh
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.9
	instance.material_override = material
	stage.add_child(instance)
	instance.position = position
	return instance

func sign_text(text: String, position: Vector3, size: int, color: Color) -> void:
	var sign := Label3D.new()
	sign.text = text
	sign.font_size = size
	sign.pixel_size = 0.007
	sign.modulate = color
	sign.outline_size = 0
	stage.add_child(sign)
	sign.position = position

func build_range() -> void:
	var world := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("839bb0")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("c0d0de")
	env.ambient_light_energy = 0.40
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	world.environment = env
	stage.add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45,-28,0)
	sun.light_color = Color("fff0d9")
	sun.light_energy = 0.75
	sun.shadow_enabled = true
	stage.add_child(sun)
	box(Vector3(0,-0.15,-5),Vector3(22,0.3,32),Color("77766e"))
	box(Vector3(0,3,-13),Vector3(22,6,0.4),Color("baa98f"))
	box(Vector3(-9,2,-5),Vector3(.4,4,16),Color("9e9b91"))
	box(Vector3(9,2,-5),Vector3(.4,4,16),Color("9e9b91"))
	for x in [-7.0,-3.5,0.0,3.5,7.0]:
		box(Vector3(x,3,-12.65),Vector3(.15,6,.25),Color("545e62"))
	box(Vector3(0,4.6,-12.5),Vector3(21,.14,.35),Color("4d5b62"))
	for z in range(-12,6,2):
		box(Vector3(0,.008,z),Vector3(18,.01,.018),Color("8e9189"))
	for x in range(-8,10,2):
		box(Vector3(x,.008,-4),Vector3(.018,.01,20),Color("8e9189"))
	for x in [-4.0,0.0,4.0]:
		box(Vector3(x,.016,-4),Vector3(.045,.018,16),Color("d0b477"))
	box(Vector3(-4.8,.7,-4),Vector3(1.8,1.4,1.7),Color("657878"))
	box(Vector3(4.9,1.1,-7),Vector3(2.6,2.2,1.5),Color("526567"))
	box(Vector3(5.2,.5,-3),Vector3(1.1,1,1.1),Color("ad9a76"))
	cover = box(Vector3(.25,.9,1.0),Vector3(1.4,1.8,.35),Color("798b8b"))
	cover.visible = false
	sign_text("KINGDOM  /  TRAINING ANNEX",Vector3(0,3.8,-12.4),60,Color("e9e5d9"))
	sign_text("01",Vector3(-5.3,2,-12.4),90,Color("6c7473"))
	sign_text("02",Vector3(5.3,2,-12.4),90,Color("6c7473"))

func walk(node: Node, type: String) -> Array:
	var found: Array = []
	if node.is_class(type): found.append(node)
	for child in node.get_children(): found.append_array(walk(child,type))
	return found

func texture_for(path: String) -> Texture2D:
	if textures.has(path): return textures[path]
	var image := Image.load_from_file(path)
	if image == null: return null
	image.generate_mipmaps()
	var result := ImageTexture.create_from_image(image)
	textures[path] = result
	return result

func make_material(info: Dictionary, directory: String, role: String, floor_y: float) -> Material:
	if str(info.get("Type", "")).contains("Glass"):
		var glass := StandardMaterial3D.new()
		glass.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		var glass_color: Dictionary = info.get("Color",{})
		glass.albedo_color = Color(glass_color.get("R",.65),glass_color.get("G",.75),glass_color.get("B",.8),float(info.get("Opacity",.2)))
		glass.roughness = float(info.get("Roughness",.3))
		if info.has("DF"): glass.albedo_texture = texture_for(directory.path_join("textures/"+str(info["DF"]).get_file()))
		return glass
	var mat := ShaderMaterial.new()
	mat.shader = shader
	mat.set_meta("role",role)
	for key in {"DF":"base", "NM":"normal", "ORM":"orm", "EM":"emission"}:
		if info.has(key):
			var map_name: String = {"DF":"base", "NM":"normal", "ORM":"orm", "EM":"emission"}[key]
			var texture := texture_for(directory.path_join("textures/" + str(info[key]).get_file()))
			if texture:
				mat.set_shader_parameter(map_name + "_map", texture)
				mat.set_shader_parameter("has_" + map_name,true)
	if info.has("Color"):
		var c: Dictionary = info["Color"]
		mat.set_shader_parameter("base_tint",Color(c.get("R",.65),c.get("G",.65),c.get("B",.65)))
	mat.set_shader_parameter("material_roughness",float(info.get("Roughness",.8)))
	mat.set_shader_parameter("material_metallic",float(info.get("Metallic",0)))
	mat.set_shader_parameter("character_floor",floor_y)
	mat.set_shader_parameter("cutout",info.get("Type","") == "Decals")
	mat.set_shader_parameter("base_uv2",info.get("BaseUV2",false))
	if info.has("Emissive"):
		var e: Dictionary = info["Emissive"]
		var c: Dictionary = e.get("Color",{})
		mat.set_shader_parameter("emission_tint",Color(c.get("R",1),c.get("G",1),c.get("B",1)))
		mat.set_shader_parameter("emission_strength",float(e.get("Intensity",1)))
	materials.append(mat)
	return mat

func load_character(slug: String) -> void:
	chosen = slug
	for actor in actors: actor.queue_free()
	actors.clear()
	players.clear()
	materials.clear()
	textures.clear()
	var directory := source_root.path_join(slug)
	var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join("viewer_config.json")))
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var error := document.append_from_file(directory.path_join(config["Model"]["Name"]), state)
	if error != OK:
		status.text = "Could not load " + slug
		push_error(status.text)
		return
	var template := document.generate_scene(state)
	var material_info: Dictionary = {}
	for info in config["Materials"]: material_info[info["Name"]] = info
	var positions := [Vector3.ZERO, Vector3(-2.5,0,-2.8), Vector3(2.4,0,-6)]
	for index in 3:
		var actor: Node3D = template if index == 0 else template.duplicate()
		stage.add_child(actor)
		actor.position = positions[index]
		actor.set_meta("role","teammate" if index == 1 else "enemy")
		actors.append(actor)
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
				mesh.set_surface_override_material(surface,make_material(info,directory,actor.get_meta("role"),0))
		for player: AnimationPlayer in walk(actor,"AnimationPlayer"):
			players.append(player)
			for animation in player.get_animation_list():
				player.get_animation(animation).loop_mode = Animation.LOOP_LINEAR
	animation_select.clear()
	if not players.is_empty():
		for animation in players[0].get_animation_list():
			if animation != "RESET": animation_select.add_item(animation)
		var preferred := "Idle"
		if not players[0].has_animation(preferred):
			preferred = animation_select.get_item_text(0) if animation_select.item_count else ""
		for index in animation_select.item_count:
			if animation_select.get_item_text(index) == preferred: animation_select.select(index)
		set_animation(preferred)
	update_materials()
	status.text = "%s loaded · %d animations\n3 actors · scene ready" % [slug.capitalize(),animation_select.item_count]
	print("CHARACTER_READY ",slug," materials=",materials.size()," animations=",animation_select.item_count)

func set_animation(animation: String) -> void:
	selected_animation = animation
	for index in animation_select.item_count:
		if animation_select.get_item_text(index) == animation: animation_select.select(index)
	for player in players:
		if player.has_animation(animation):
			player.play(animation)
			player.advance(0)
			player.speed_scale = 1.0 if playing else 0.0

func update_materials() -> void:
	for mat in materials:
		mat.set_shader_parameter("rim_color",ALLY if mat.get_meta("role") == "teammate" else purple)
		mat.set_shader_parameter("rim_enabled",rim_enabled)
		mat.set_shader_parameter("rim_strength",rim_strength * (0.45 if mat.get_meta("role") == "teammate" else 1.0))
		mat.set_shader_parameter("rim_power",rim_power)
		mat.set_shader_parameter("upper_bias",upper_bias)

func update_camera() -> void:
	if not camera: return
	camera.position = target + Vector3(sin(orbit_yaw)*cos(orbit_pitch),sin(orbit_pitch),cos(orbit_yaw)*cos(orbit_pitch))*distance
	camera.look_at(target)

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT: rotating = event.pressed
		if get_global_mouse_position().x > 318 and event.pressed:
			if event.button_index == MOUSE_BUTTON_WHEEL_UP: distance = max(1.5,distance*.9); update_camera()
			if event.button_index == MOUSE_BUTTON_WHEEL_DOWN: distance = min(30,distance*1.1); update_camera()
	if event is InputEventMouseMotion and rotating:
		orbit_yaw -= event.relative.x*.006
		orbit_pitch = clamp(orbit_pitch+event.relative.y*.005,-.45,1.1)
		update_camera()
	if event is InputEventKey and event.pressed and event.keycode == KEY_F12: capture()

func _process(delta: float) -> void:
	if spin:
		for actor in actors: actor.rotation.y += delta*.35
	var focused := get_viewport().gui_get_focus_owner()
	if focused is LineEdit or focused is TextEdit: return
	var move := Vector3.ZERO
	if Input.is_physical_key_pressed(KEY_A): move.x -= 1
	if Input.is_physical_key_pressed(KEY_D): move.x += 1
	if Input.is_physical_key_pressed(KEY_W): move.z -= 1
	if Input.is_physical_key_pressed(KEY_S): move.z += 1
	if Input.is_physical_key_pressed(KEY_Q): move.y -= 1
	if Input.is_physical_key_pressed(KEY_E): move.y += 1
	if move != Vector3.ZERO: target += move * delta * 2; update_camera()

func capture(prefix: String = "") -> void:
	if capture_busy: return
	capture_busy = true
	var original_size := viewport.size
	viewport_container.stretch = false
	viewport.size = Vector2i(1920,1080)
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var folder := ProjectSettings.globalize_path("res://captures")
	DirAccess.make_dir_recursive_absolute(folder)
	if prefix.is_empty(): prefix = chosen + "_" + str(Time.get_unix_time_from_system()).replace(".","_")
	var path := folder.path_join(prefix)
	var result := viewport.get_texture().get_image().save_png(path + ".png")
	var actor_data: Array = []
	for actor in actors:
		actor_data.append({"role":actor.get_meta("role"),"position":[actor.position.x,actor.position.y,actor.position.z],"rotation_y":actor.rotation.y})
	var meta := {"character":chosen,"animation":selected_animation,"actors":actor_data,"purple_srgb_hex":purple.to_html(false),"color_status":"Screenshot estimate; not an official shader constant", "rim_enabled":rim_enabled,"rim_strength":rim_strength,"rim_power":rim_power,"upper_bias":upper_bias,"cover_visible":cover.visible,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"vertical_fov":camera.fov,"resolution":[viewport.size.x,viewport.size.y]}
	FileAccess.open(path+".json",FileAccess.WRITE).store_string(JSON.stringify(meta,"\t"))
	status.text = "Saved " + prefix + ".png" if result == OK else "Capture failed"
	print("CAPTURE ",path,".png")
	viewport.size = original_size
	viewport_container.stretch = true
	capture_busy = false

func verify_scene() -> void:
	playing = false
	for player in players: player.speed_scale = 0
	await get_tree().create_timer(1.0).timeout
	await capture("verify_purple")
	rim_enabled = false
	update_materials()
	await get_tree().create_timer(.3).timeout
	await capture("verify_no_highlight")
	rim_enabled = true
	update_materials()
	cover.visible = true
	await get_tree().create_timer(.3).timeout
	await capture("verify_cover")
	rim_enabled = false
	update_materials()
	await get_tree().create_timer(.3).timeout
	await capture("verify_cover_no_highlight")
	rim_enabled = true
	update_materials()
	cover.visible = false
	for slug in ["jett","kayo","gekko"]:
		load_character(slug)
		await get_tree().create_timer(.5).timeout
		await capture("verify_"+slug)
	load_character("viper")
	set_animation("CS_Pandemic_S0_CharSelect_Idle")
	for player in players: player.seek(1.0,true)
	await get_tree().create_timer(.5).timeout
	await capture("verify_animation")
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png("res://captures/render_lab_ui.png")
