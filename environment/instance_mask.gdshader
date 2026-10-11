shader_type spatial;
render_mode unshaded, cull_disabled, fog_disabled;
uniform float instance_value = 0.125490196;
uniform sampler2D base_map : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool has_base = false;
uniform bool cutout = false;
uniform bool base_uv2 = false;
uniform mat4 head_world_to_local;
varying vec3 world_position;
void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}
void fragment() {
    if (cutout && has_base && texture(base_map, base_uv2 ? UV2 : UV).a < 0.35) { discard; }
    vec3 h = (head_world_to_local * vec4(world_position, 1.0)).xyz;
    bool in_head = h.y >= -0.115 && h.y <= 0.30 && abs(h.x) <= 0.25 && abs(h.z) <= 0.20;
    ALBEDO = vec3(instance_value, (in_head ? step(0.5, COLOR.r) : 0.0), 0.0);
}
