shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx, cull_disabled;

uniform sampler2D base_map : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_map : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D orm_map : filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D emission_map : filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool has_base = false;
uniform bool has_normal = false;
uniform bool has_orm = false;
uniform bool has_emission = false;
uniform vec3 base_tint : source_color = vec3(0.65);
uniform vec3 emission_tint : source_color = vec3(1.0);
uniform float emission_strength = 0.0;
uniform float material_roughness = 0.8;
uniform float material_metallic = 0.0;
uniform bool cutout = false;
uniform bool rim_enabled = true;
// Screenshot estimate, not an official Riot uniform value.
uniform vec3 rim_color : source_color = vec3(0.690196, 0.301961, 0.745098);
uniform float rim_strength : hint_range(0.0, 3.0) = 2.2;
uniform float rim_power : hint_range(0.5, 8.0) = 2.5;
uniform float upper_bias : hint_range(0.0, 1.0) = 0.6;
uniform bool base_uv2 = false;
uniform float character_floor = 0.0;
uniform float character_height = 2.1;
varying vec3 world_position;
varying vec3 world_normal;

void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    world_normal = normalize(MODEL_NORMAL_MATRIX * NORMAL);
}

void fragment() {
    vec4 base = has_base ? texture(base_map, base_uv2 ? UV2 : UV) : vec4(base_tint, 1.0);
    if (cutout && base.a < 0.35) { discard; }
    ALBEDO = base.rgb;
    ROUGHNESS = material_roughness;
    METALLIC = material_metallic;
    if (has_orm) {
        vec3 orm = texture(orm_map, UV).rgb;
        AO = orm.r;
        ROUGHNESS = max(0.28, orm.g * material_roughness);
        METALLIC = orm.b * material_metallic;
    }
    if (has_normal) { NORMAL_MAP = texture(normal_map, UV).rgb; }
    EMISSION = has_emission ? texture(emission_map, UV).rgb * emission_tint * emission_strength : vec3(0.0);
    float facing = clamp(dot(normalize(NORMAL), normalize(VIEW)), 0.0, 1.0);
    float fresnel = pow(1.0 - facing, rim_power);
    float height_mask = smoothstep(0.12, 0.80, (world_position.y - character_floor) / character_height);
    float up_mask = smoothstep(-0.65, 0.35, normalize(world_normal).y);
    float directional_mask = mix(1.0, mix(0.30, 1.0, height_mask) * mix(0.30, 1.0, up_mask), upper_bias);
    float rim = rim_enabled ? fresnel * directional_mask * rim_strength : 0.0;
    // Keep the base surface shading and add a colored grazing-angle light.
    EMISSION += rim_color * rim;
}
