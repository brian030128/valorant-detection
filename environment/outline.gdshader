shader_type spatial;
render_mode unshaded, cull_front, fog_disabled;
uniform bool outline_enabled = true;
uniform float width_pixels = 2.25;
uniform vec3 outline_color : source_color = vec3(0.690196, 0.301961, 0.745098);
uniform bool mask_pass = false;
uniform float instance_value = 0.125490196;
uniform mat4 head_world_to_local;
uniform bool cutout = false;
uniform bool has_base = false;
uniform bool base_uv2 = false;
uniform sampler2D base_map : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
varying vec3 world_position;
void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vec4 clip = PROJECTION_MATRIX * MODELVIEW_MATRIX * vec4(VERTEX, 1.0);
    // Push only depth back by 3 cm. This suppresses interior triangle speckles
    // on open, multi-material character-select meshes while preserving XY width.
    vec4 view_position = MODELVIEW_MATRIX * vec4(VERTEX, 1.0);
    view_position.z -= 0.03;
    vec4 depth_clip = PROJECTION_MATRIX * view_position;
    clip.z = (depth_clip.z / depth_clip.w) * clip.w;
    vec3 view_normal = normalize(MODELVIEW_NORMAL_MATRIX * NORMAL);
    vec2 direction = (PROJECTION_MATRIX * vec4(view_normal, 0.0)).xy;
    float length_xy = length(direction);
    if (length_xy > 0.0001) {
        clip.xy += direction / length_xy * (2.0 * width_pixels / VIEWPORT_SIZE) * clip.w;
    }
    POSITION = clip;
}
void fragment() {
    if (!outline_enabled) { discard; }
    if (cutout && has_base && texture(base_map, base_uv2 ? UV2 : UV).a < 0.35) { discard; }
    if (mask_pass) {
        vec3 h = (head_world_to_local * vec4(world_position, 1.0)).xyz;
        bool in_head = h.y >= -0.115 && h.y <= 0.30 && abs(h.x) <= 0.25 && abs(h.z) <= 0.20;
        ALBEDO = vec3(instance_value, in_head ? step(0.5, COLOR.r) : 0.0, 0.0);
    } else {
        ALBEDO = outline_color;
        EMISSION = outline_color * 0.18;
    }
}
