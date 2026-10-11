extends "res://center_dataset.gd"

const THEMES = ["scaffold_canyon","lattice_bridge","pipeworks","refinery_tanks","steel_foundry","loading_docks","cable_tunnels","pallet_depot","transit_concourse","cooling_plant","antenna_yard","brick_quarter","concrete_bunker","solar_array","quarry_terraces","timber_sawmill","botanical_courts","arcade_shops","maintenance_bays","flood_barriers"]
const LAYOUTS = ["parallel_lanes","wide_court","staggered_islands","diagonal_bays","stepped_setbacks","cross_gallery"]
const SCENE_START := 600000
var design_id := 0
var theme_id := 0
var layout_id := 0
var design_seed := 0
var target_cover: MeshInstance3D
var surface_color := Color("858b89")

func scene_name() -> String:
	return THEMES[theme_id]+"__"+LAYOUTS[layout_id]

func build_scene(group: int) -> void:
	target_cover = null
	super.build_scene(group)
	for item in scenery: item.free()
	scenery.clear()
	for label in labels_3d: label.free()
	labels_3d.clear()
	design_id = ((group-SCENE_START/per_group)/2)%120
	theme_id = design_id/6
	layout_id = design_id%6
	design_seed = 3761927+group*104729+design_id*15485863
	rng.seed = design_seed
	var palettes = [Color("8b8070"),Color("5c7684"),Color("54746d"),Color("a8a197"),Color("585c67"),Color("947759"),Color("666584"),Color("9b8360"),Color("919d9e"),Color("78979b"),Color("797c86"),Color("b28773"),Color("858d87"),Color("5b7797"),Color("a19478"),Color("937b55"),Color("697955"),Color("a39287"),Color("667e8b"),Color("8a989a")]
	surface_color = palettes[theme_id]
	block(Vector3(0,-.2,-10),Vector3(70,.4,115),surface_color.darkened(.17))
	for side in [-1,1]:
		for bay in 9:
			if layout_id==2 and (bay+side+1)%3==1: continue
			var z := 12.0-bay*5.8
			var x: float = side*(4.8+rng.randf_range(-.25,.5))
			var yaw := 0.0
			var elevation := 0.0
			if layout_id==1: x = side*(7.5+abs(bay-4)*.25)
			if layout_id==2:
				x = side*(4.4+(bay%3)*1.2)
				z += side*1.2
			if layout_id==3:
				x = side*6.1
				z += side*1.8
				yaw = side*.52
			if layout_id==4:
				x = side*(4.5+(bay%4)*.8)
				elevation = (bay%3)*.35
			if layout_id==5:
				x = side*(5.0 if bay%3==0 else 7.8)
				z += side*.8
			var pivot := Vector3(x,elevation,z)
			var before := scenery.size()
			module(pivot,side,bay)
			for i in range(before,scenery.size()):
				var mesh := scenery[i]
				mesh.position = pivot+(mesh.position-pivot).rotated(Vector3.UP,yaw)
				mesh.rotate_y(yaw)
	if layout_id==1:
		for z in [-4,-19,-34]:
			for side in [-1,1]:
				cylinder(Vector3(side*4.5,1.4,z),.4,2.8,surface_color.lightened(.2))
	if layout_id==5:
		for z in [7,-10,-27]:
			block(Vector3(0,4.7,z),Vector3(17,.35,2.1),surface_color.darkened(.15))
			for side in [-1,1]:block(Vector3(side*7.8,2.3,z),Vector3(.5,4.6,.5),surface_color)
	if theme_id in [4,6,8,12,18]:
		var roof_height := 6.6 if layout_id!=5 else 7.5
		block(Vector3(0,roof_height,-12),Vector3(24,.3,67),surface_color.darkened(.3))
		for bay in 10:
			block(Vector3(0,roof_height-.3,14-bay*5.8),Vector3(2.2,.08,.25),Color("d7d8be"))
	for k in 7:
		var h := rng.randf_range(.35,1.5)
		var x: float = (-1 if k%2==0 else 1)*rng.randf_range(2.9,4.2)
		block(Vector3(x,h/2,rng.randf_range(-30,5)),Vector3(rng.randf_range(.4,1.2),h,rng.randf_range(.5,1.4)),surface_color.lightened(.12))
	block(Vector3(0,2.4,-43),Vector3(26,4.8,.4),surface_color.darkened(.12))

func module(p: Vector3, side: int, bay: int) -> void:
	var c := surface_color.lightened(rng.randf_range(-.1,.1))
	var metal := Color("909fa5")
	var wood := Color("bc9a62")
	if theme_id==0: # Multi-level scaffolding with cross braces.
		block(p+Vector3(side*1.4,2,0),Vector3(2.3,4,4.9),c)
		for level in 3:
			block(p+Vector3(-side*.3,.55+level*1.7,0),Vector3(1.7,.12,5),wood)
			for dz in [-2.2,2.2]:cylinder(p+Vector3(-side*1.1,2.6,dz),.065,5.2,metal)
			var brace := block(p+Vector3(-side*1.15,1.2+level*1.2,0),Vector3(.09,.09,4.7),metal)
			brace.rotation.x = .65 if (bay+level)%2 else -.65
	elif theme_id==1: # Triangular steel trusses and guard rails.
		for dz in [-2.3,2.3]:block(p+Vector3(0,2.5,dz),Vector3(.18,5,.18),metal)
		for h in [.6,2.0,4.7]:block(p+Vector3(0,h,0),Vector3(.16,.16,5),c)
		for k in 4:
			var beam := block(p+Vector3(0,2.3,-1.8+k*1.2),Vector3(.12,4.6,.12),metal)
			beam.rotation.x = .33 if k%2 else -.33
	elif theme_id==2: # Banks of pipes and valve hubs.
		for k in 5:
			var pipe := cylinder(p+Vector3(side*.45*k,.8+k*.42,0),.2,5,c.lightened(.13))
			pipe.rotation.x = PI/2
		for dz in [-1.8,1.8]:
			block(p+Vector3(side*.7,1.7,dz),Vector3(2.8,.16,.16),metal)
			cylinder(p+Vector3(-side*.25,1.5,dz),.38,.24,Color("a06745"))
	elif theme_id==3: # Cylindrical storage tanks.
		cylinder(p+Vector3(side*.8,2.4,0),1.4,4.8,c)
		for h in [.5,2.4,4.3]:cylinder(p+Vector3(side*.8,h,0),1.43,.12,metal)
		for k in 10:block(p+Vector3(-side*.64,.4+k*.4,0),Vector3(.1,.08,.65),metal)
	elif theme_id==4: # Furnaces and overhead exhaust ducting.
		block(p+Vector3(side*.6,1.7,0),Vector3(2.7,3.4,3.5),c)
		block(p+Vector3(-side*.8,1.3,0),Vector3(.12,1.6,1.7),Color("c58146"))
		cylinder(p+Vector3(side*.6,4.7,0),.45,3,metal)
	elif theme_id==5: # Shuttered loading docks and bumpers.
		block(p+Vector3(side*1,2.8,0),Vector3(2,5.6,5.4),c)
		for row in 11:block(p+Vector3(-side*.06,.7+row*.35,0),Vector3(.08,.2,3.3),metal)
		block(p+Vector3(-side*.8,.4,0),Vector3(1.6,.8,4),c.darkened(.25))
	elif theme_id==6: # Cable trays, cabinets and repeated bundled conduits.
		block(p+Vector3(side*.8,2.8,0),Vector3(1,5.6,5.4),c)
		for k in 8:
			var cable := cylinder(p+Vector3(-side*.1,1+k*.35,0),.055,5.5,metal.darkened(.2))
			cable.rotation.x = PI/2
		block(p+Vector3(-side*.35,1.1,1),Vector3(.7,2.2,1.1),Color("a6a096"))
	elif theme_id==7: # Uneven pallet stacks and wooden slats.
		for stack in 3:
			var h: int = rng.randi_range(2,6)
			for row in h:
				for slat in 5:block(p+Vector3(side*.5*stack,.15+row*.27,-1.5+slat*.55),Vector3(2,.12,.27),wood.darkened(stack*.08))
	elif theme_id==8: # Concourse columns, ticket machines and signage.
		cylinder(p+Vector3(side*.7,2.7,0),.5,5.4,c)
		block(p+Vector3(-side*.25,1.1,1.5),Vector3(.9,2.2,.7),Color("576b78"))
		block(p+Vector3(-side*.74,1.5,1.5),Vector3(.05,.5,.5),Color("70aeb0"))
		block(p+Vector3(-side*.4,3.8,-1),Vector3(1.8,.5,1.3),Color("435977"))
	elif theme_id==9: # Finned cooling equipment and fans.
		block(p+Vector3(side*.6,1.5,0),Vector3(2.5,3,4.5),c)
		for k in 14:block(p+Vector3(-side*.7,1.5,-2+k*.3),Vector3(.08,2.7,.06),metal)
		for dz in [-1,1]:cylinder(p+Vector3(side*.6,3.1,dz),.6,.15,metal.darkened(.3))
	elif theme_id==10: # Antenna masts and tilted dishes.
		cylinder(p+Vector3(side*.8,3.1,0),.16,6.2,metal)
		for h in [2.5,4.8]:
			var dish := cylinder(p+Vector3(0,h,0),.8,.16,c)
			dish.rotation.z = side*1.2
		block(p+Vector3(side*.8,.5,0),Vector3(2.2,1,2.2),c.darkened(.2))
	elif theme_id==11: # Recessed doors, shutters, and brick courses.
		block(p+Vector3(side*.8,3,0),Vector3(2,6,5.4),c)
		for row in 9:block(p+Vector3(-side*.23,.35+row*.6,0),Vector3(.04,.025,5.3),c.darkened(.28))
		block(p+Vector3(-side*.26,1.4,0),Vector3(.06,2.8,1.1),Color("465861"))
		for dz in [-1.7,1.7]:block(p+Vector3(-side*.3,3.8,dz),Vector3(.1,1.5,.8),Color("6e8790"))
	elif theme_id==12: # Angled bunker buttresses and inset walls.
		block(p+Vector3(side*1,2.8,0),Vector3(2,5.6,5.3),c)
		for dz in [-2,2]:
			var buttress := block(p+Vector3(-side*.1,1.8,dz),Vector3(1,3.6,.7),c.lightened(.12))
			buttress.rotation.z = side*.2
		block(p+Vector3(-side*.15,2.4,0),Vector3(.1,.65,2.2),Color("3b464a"))
	elif theme_id==13: # Tilted panel arrays with repeated cell patterns.
		for dz in [-1.3,1.3]:
			cylinder(p+Vector3(side*.6,1,dz),.08,2,metal)
			var panel := block(p+Vector3(side*.6,2,dz),Vector3(3,.15,2.3),Color("365d85"))
			panel.rotation.z = side*.3
			for k in 5:block(p+Vector3(side*.6,2.25,dz-.9+k*.45),Vector3(2.8,.03,.035),Color("99b5c2"))
	elif theme_id==14: # Offset quarry ledges and angular rock blocks.
		for level in 4:
			var rock := block(p+Vector3(side*level*.55,.55+level*.85,0),Vector3(2.4,1.1,4.8-level*.3),c.lightened(level*.04))
			rock.rotation.y = rng.randf_range(-.12,.12)
	elif theme_id==15: # Log piles and sawmill platforms.
		for row in 3:
			for k in range(3-row):
				var log_mesh := cylinder(p+Vector3(side*(.3+k*.6+row*.3),.35+row*.6,0),.3,4.5,wood.darkened(.2))
				log_mesh.rotation.x = PI/2
		block(p+Vector3(-side*.6,.7,0),Vector3(.6,1.4,4.8),c.darkened(.2))
	elif theme_id==16: # Trellises and staggered planters.
		block(p+Vector3(side*.5,.45,0),Vector3(2.4,.9,4.7),Color("907457"))
		for k in 5:
			cylinder(p+Vector3(side*.6,1.5,-1.7+k*.8),.06,2.2,wood)
			var plant := block(p+Vector3(side*.6,2,-1.7+k*.8),Vector3(.9,1.3,.6),Color("507244"))
			plant.rotation.z = rng.randf_range(-.5,.5)
		for h in [1.4,2.7]:block(p+Vector3(side*.65,h,0),Vector3(.07,.07,5),wood)
	elif theme_id==17: # Shop awnings and display cases.
		block(p+Vector3(side*.8,2.5,0),Vector3(2,5,5.5),c)
		block(p+Vector3(-side*.25,1.8,0),Vector3(.1,2.6,3.9),Color("345962"))
		block(p+Vector3(-side*.7,3.3,0),Vector3(1.3,.15,4.7),Color.from_hsv(rng.randf(),.45,.7))
		block(p+Vector3(-side*.8,.6,0),Vector3(.8,1.2,3),wood)
	elif theme_id==18: # Service lifts and tool chests.
		for dz in [-1.7,1.7]:block(p+Vector3(side*.5,2.4,dz),Vector3(.35,4.8,.35),Color("b3944c"))
		block(p+Vector3(side*.5,3.4,0),Vector3(2,.2,4),metal)
		block(p+Vector3(-side*.35,.9,0),Vector3(1.2,1.8,2),Color("984e47"))
		for h in [.4,.8,1.2,1.6]:block(p+Vector3(-side*.98,h,0),Vector3(.05,.05,1.8),metal)
	else: # Flood gates, railings and ribbed retaining walls.
		block(p+Vector3(side*.8,1.4,0),Vector3(2.2,2.8,5.3),c)
		for k in 7:block(p+Vector3(-side*.35,1.4,-2.3+k*.7),Vector3(.18,2.5,.18),metal)
		for dz in [-2,0,2]:cylinder(p+Vector3(-side*.55,2.9,dz),.055,1.3,metal)
		block(p+Vector3(-side*.55,3.5,0),Vector3(.07,.07,5),metal)

func category(index: int) -> String:
	return ["tiny_head","tiny_head","small_head","small_head","normal_scale","normal_scale","partial_cover","partial_cover","background_negative","background_negative"][index%10]

func frame_index(index: int) -> int:
	return index*20+1+(index/10)%4

func center_frame(index: int, attempt: int) -> Array:
	if is_instance_valid(target_cover):
		scenery.erase(target_cover)
		target_cover.free()
		target_cover = null
	var records := super.center_frame(frame_index(index),attempt)
	var kind := category(index)
	if kind=="background_negative":
		for actor in actors: actor.visible = false
		return []
	var record: Dictionary = records[0]
	var k: int = int(record["instance_id"])-1
	var actor: Node3D = actors[k]
	var head_world: Vector3 = head_transforms[k].affine_inverse().origin
	if kind in ["tiny_head","small_head","normal_scale"]:
		var distance := rng.randf_range(28,43) if kind=="tiny_head" else rng.randf_range(15,28) if kind=="small_head" else rng.randf_range(5,23)
		camera.position = actor.position+Vector3(rng.randf_range(-2,2),rng.randf_range(1.4,2.2),distance)
		camera.look_at(head_world.lerp(actor.position+Vector3.UP,.3),Vector3.UP)
		camera.rotate_object_local(Vector3.UP,rng.randf_range(-.1,.1))
		camera.rotate_object_local(Vector3.RIGHT,rng.randf_range(-.1,.1))
	else:
		camera.look_at(head_world.lerp(actor.position+Vector3.UP,.3),Vector3.UP)
		var point := camera.position.lerp(head_world,.82)
		point += camera.global_basis.x*rng.randf_range(.07,.22)
		target_cover = block(point,Vector3(rng.randf_range(.15,.35),rng.randf_range(1.6,3.5),rng.randf_range(.15,.35)),surface_color.lightened(rng.randf_range(-.15,.15)))
		target_cover.rotation.y = camera.rotation.y
	var role := "teammate" if index%4==0 else "enemy"
	record["role"] = role
	actor.set_meta("role",role)
	for item in actor_surfaces:
		var mat: Material = item["beauty"]
		if mat is ShaderMaterial:
			mat.set_shader_parameter("rim_color",PURPLE if role=="enemy" else ALLY)
			mat.set_shader_parameter("rim_strength",2.2 if role=="enemy" else .99)
	return records

func generate() -> void:
	base_seed = 20261117
	viewport.size = Vector2i(CROP_SIZE,CROP_SIZE)
	camera.fov = rad_to_deg(2*atan(tan(deg_to_rad(70.53)/2)*float(CROP_SIZE)/1080.0))
	for index in range(first,first+total):
		if "--negative-only" in OS.get_cmdline_user_args() and category(index)!="background_negative": continue
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
			if category(index)=="partial_cover":
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
			# Reject empty/imperceptible positives; partial-cover cases retain visible head pixels.
			if not records.is_empty() and (body_pixels<40 or head_pixels<3): continue
			var short_side := mini(head_max.x-head_min.x+1,head_max.y-head_min.y+1)
			if category(index) in ["tiny_head","small_head"] and (short_side<2 or short_side>=16): continue
			if category(index)=="tiny_head" and short_side>=8: continue
			if category(index)=="partial_cover" and (head_pixels>uncovered_head_pixels*.9 or head_pixels<uncovered_head_pixels*.15): continue
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
			var meta := {"index":index,"split":split,"scene_group":group,"scene_family":scene_name(),"scene_seed":base_seed+group*7919,"frame_seed":20261013+frame_index(index)*104729+attempt*15485863,"actors":records,"resolution":[400,400],"vertical_fov":camera.fov,"camera_position":[camera.position.x,camera.position.y,camera.position.z],"camera_rotation_degrees":[camera.rotation_degrees.x,camera.rotation_degrees.y,camera.rotation_degrees.z],"purple_srgb":"#b04dbe","generator_version":"hundred-scenes-v1","acceptance_attempt":attempt,"visible_body_pixels":body_pixels,"visible_head_pixels":head_pixels}
			meta["crop"]={"source_resolution":[1920,1080],"xyxy":[760,340,1160,740],"source_vertical_fov":70.53,"method":"Equivalent central perspective subfrustum, no resizing or upscaling"}
			meta["target_category"] = category(index)
			meta["head_short_side"] = short_side
			meta["uncovered_head_pixels"] = uncovered_head_pixels
			meta["scene_seed"] = design_seed
			meta["structural_theme"] = THEMES[theme_id]
			meta["spatial_layout"] = LAYOUTS[layout_id]
			meta["scene_design_id"] = design_id
			meta["layout_seed_index"] = (group-SCENE_START/per_group)%2
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
