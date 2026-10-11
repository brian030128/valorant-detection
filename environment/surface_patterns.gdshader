shader_type spatial;
render_mode cull_back;
uniform vec4 base_color : source_color = vec4(0.5,0.5,0.5,1.0);
uniform int pattern = 0;
uniform float scale_m = 1.0;
uniform float texture_amount = 1.0;
varying vec3 world_pos;
varying vec3 world_normal;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise2(vec2 p){vec2 i=floor(p);vec2 f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
void vertex(){world_pos=(MODEL_MATRIX*vec4(VERTEX,1.0)).xyz;world_normal=normalize(mat3(MODEL_MATRIX)*NORMAL);}
void fragment(){
 vec3 n=abs(normalize(world_normal));
 vec2 p=world_pos.xz;
 if(n.x>n.y && n.x>n.z){p=world_pos.zy;}else if(n.z>n.y){p=world_pos.xy;}
 p*=scale_m;
 float grain=noise2(p*35.0);float broad=noise2(p*1.7);vec3 c=base_color.rgb;
 if(pattern==0){c*=0.65+0.5*broad+0.2*grain;}
 else if(pattern==1){vec2 q=p*vec2(2.0,4.0);q.x+=mod(floor(q.y),2.0)*0.5;vec2 f=fract(q);float mortar=step(f.x,0.055)+step(f.y,0.10);c=mix(c*(0.65+0.6*hash(floor(q))),vec3(0.65,0.62,0.55),clamp(mortar,0.0,1.0));}
 else if(pattern==2){vec2 q=p*3.0;vec2 f=fract(q);float seam=max(step(f.x,0.035),step(f.y,0.035));c=mix(c*(0.75+0.4*hash(floor(q))),vec3(0.13),seam);}
 else if(pattern==3){float g=sin(p.x*95.0+noise2(p*vec2(5,0.5))*16.0);c*=0.7+0.18*g+0.25*broad;float joint=step(fract(p.x*2.0),0.025);c*=1.0-joint*0.6;}
 else if(pattern==4){float rust=smoothstep(0.35,0.65,broad+0.2*grain);c=mix(c*(0.8+grain*0.3),vec3(0.48,0.20,0.075)*(0.6+grain*0.6),rust);}
 else if(pattern==5){float stripe=step(0.5,fract((p.x+p.y)*2.5));c=mix(vec3(0.065),vec3(0.9,0.66,0.12),stripe);}
 else if(pattern==6){float strokes=smoothstep(0.08,0.025,abs(sin(p.x*3.2+sin(p.y*4.0))));vec3 ink=mix(vec3(0.69,0.30,0.75),vec3(0.12,0.65,0.72),step(0.5,noise2(p)));c=mix(c*(0.8+0.2*grain),ink,strokes);}
 else {vec2 q=p*7.0;vec2 f=fract(q);float seam=max(step(f.x,0.07),step(f.y,0.07));float h=hash(floor(q));c=mix(c*(0.35+h),vec3(0.19),seam);}
 ALBEDO=mix(base_color.rgb,clamp(c,vec3(0.015),vec3(0.95)),texture_amount);ROUGHNESS=0.85;
}
