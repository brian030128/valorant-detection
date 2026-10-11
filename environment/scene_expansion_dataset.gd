extends "res://targeted_dataset.gd"

const EXPANSION_MAPS = ["market_street", "server_room", "aircraft_hangar", "wooded_path", "canal_walk", "parking_garage", "stone_ruins", "ice_tunnel"]

func scene_name() -> String:
	return EXPANSION_MAPS[active_map]

func build_scene(group: int) -> void:
	super.build_scene(group)
	for item in scenery: item.free()
	scenery.clear()
	for label in labels_3d: label.free()
	labels_3d.clear()
	active_map = group%8
	rng.seed = 734921+group*7919+active_map*100003
	var floors = [Color("a9977e"),Color("33404b"),Color("69737a"),Color("605c3b"),Color("89847a"),Color("53565d"),Color("827f6a"),Color("93b9c7")]
	var floor_color: Color = floors[active_map]
	block(Vector3(0,-.2,-8),Vector3(65,.4,110),floor_color)
	for side in [-1,1]:
		for bay in 10:
			var z := 12.0-bay*5.3
			var x: float = side*rng.randf_range(4.7,6.7)
			if active_map==0:
				var facade := Color.from_hsv(rng.randf(),.2,rng.randf_range(.55,.9))
				block(Vector3(x,3,z),Vector3(3,6,4.8),facade)
				block(Vector3(x-side*1.6,2.7,z),Vector3(1.5,.15,3.6),Color("a74738") if bay%2 else Color("467785"))
				block(Vector3(x-side*1.9,.6,z),Vector3(.9,1.2,2.8),Color("816348"))
				for k in 5:
					block(Vector3(x-side*1.9,1.3,z-1+k*.5),Vector3(.35,.25,.35),Color("c9a345") if k%2 else Color("68894c"))
				block(Vector3(x-side*1.52,4,z),Vector3(.08,1.5,1.2),Color("314453"))
			elif active_map==1:
				block(Vector3(x,1.8,z),Vector3(1.4,3.6,3.6),Color("273543"))
				for row in 9:
					block(Vector3(x-side*.73,.3+row*.35,z),Vector3(.06,.18,3.2),Color("566875"))
					block(Vector3(x-side*.78,.3+row*.35,z-.8),Vector3(.04,.07,.15),Color("63bba5"))
				block(Vector3(side*8,2.5,z),Vector3(.4,5,5.3),Color("a5acaa"))
			elif active_map==2:
				block(Vector3(side*10,4,z),Vector3(.4,8,5.3),Color("80919b"))
				block(Vector3(side*9,4,z),Vector3(.4,8,.4),Color("b2ac8c"))
				if bay%3==0:
					var fuselage := cylinder(Vector3(side*7,1.6,z),.9,5,Color("c2c8c5"))
					fuselage.rotation.x = PI/2
					block(Vector3(side*7,1.3,z),Vector3(5,.15,1.5),Color("a7b4bf"))
				block(Vector3(side*4,.02,z),Vector3(.15,.02,4.5),Color("c6b24b"))
			elif active_map==3:
				cylinder(Vector3(x,2.8,z),rng.randf_range(.25,.5),5.6,Color("6c503b"))
				for k in 3:
					var canopy := block(Vector3(x+rng.randf_range(-1,1),4.6+k*.9,z),Vector3(3.8-k*.6,1.8,3.8-k*.6),Color("536e43").darkened(k*.08))
					canopy.rotation.y = rng.randf_range(-PI,PI)
				block(Vector3(x,.45,z+1.8),Vector3(1.3,.9,1.2),Color("777b67"))
			elif active_map==4:
				block(Vector3(side*7,-.05,z),Vector3(4,.1,5.3),Color("438994"))
				block(Vector3(side*4.5,.25,z),Vector3(.35,.5,5.3),Color("b3afa0"))
				cylinder(Vector3(side*4.3,.8,z),.07,1.6,Color("445a63"))
				block(Vector3(side*4.3,1.5,z),Vector3(.08,.08,5.3),Color("445a63"))
				block(Vector3(side*10,3,z),Vector3(2,6,5),Color("ad9477"))
			elif active_map==5:
				block(Vector3(side*5,2,z),Vector3(.8,4,.8),Color("999991"))
				block(Vector3(side*5,1,z),Vector3(.84,.4,.84),Color("dbb541"))
				var car_color := Color.from_hsv(rng.randf(),.5,.55)
				block(Vector3(side*7,.6,z),Vector3(2,1.2,3.8),car_color)
				block(Vector3(side*7,1.4,z),Vector3(1.8,.7,2),Color("37464f"))
				block(Vector3(side*5,.02,z+2.3),Vector3(5,.02,.08),Color("c5c4af"))
			elif active_map==6:
				var h := rng.randf_range(2,5)
				cylinder(Vector3(x,h/2,z),.6,h,Color("a19b80"))
				block(Vector3(x,h,z),Vector3(1.5,.4,1.5),Color("b6ad8e"))
				if bay%2==0:
					block(Vector3(x,1.3,z+2),Vector3(.9,2.6,3),Color("8e8873"))
				var rock := block(Vector3(x-side*.5,.35,z+1),Vector3(1.3,.7,1.1),Color("757763"))
				rock.rotation.y = rng.randf_range(-PI,PI)
			else:
				var ice := block(Vector3(x,2.6,z),Vector3(2.5,5.2,5.7),Color("a6cbd4").darkened(rng.randf_range(0,.25)))
				ice.rotation.z = side*rng.randf_range(-.2,.2)
				ice.rotation.y = rng.randf_range(-.2,.2)
				var spike := cylinder(Vector3(x-side*.5,.7,z+1),.4,1.4,Color("bcdde1"))
				spike.rotation.z = side*.3
	if active_map in [1,2,5,7]:
		var height := 8.5 if active_map==2 else 5.5
		block(Vector3(0,height,-10),Vector3(23,.3,70),floor_color.darkened(.2))
		for k in 12:
			block(Vector3(0,height-.25,14-k*5.3),Vector3(12,.2,.35),Color("c4d2d2"))
			block(Vector3(0,height-.42,14-k*5.3),Vector3(2,.05,.2),Color("e5e2c6"))
	for k in 8:
		var x: float = (-1 if k%2==0 else 1)*rng.randf_range(2.8,4)
		var h := rng.randf_range(.4,1.5)
		block(Vector3(x,h/2,rng.randf_range(-29,7)),Vector3(rng.randf_range(.5,1.1),h,.9),floor_color.lightened(.12))
	block(Vector3(0,2.5,-43),Vector3(24,5,.5),floor_color.darkened(.15))
