"""Build the first-party Structara Books-to-Knowledge-Plane hero master.

Run with Blender 4.5 LTS:
    blender --background --python tools/assets/build_structara_hero.py

The scene intentionally uses only procedural geometry, Blender's bundled font,
and the approved Structara material palette. No external mesh, HDRI, texture,
image, or generated source is used.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
MASTER_DIR = ROOT / "assets" / "3d" / "master"
DERIVATIVE_DIR = ROOT / "assets" / "3d" / "derivatives"
PUBLIC_DIR = ROOT / "apps" / "web" / "public" / "hero"

for directory in (MASTER_DIR, DERIVATIVE_DIR, PUBLIC_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.materials,
        bpy.data.curves,
        bpy.data.meshes,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.55,
    emission: tuple[float, float, float, float] | None = None,
) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    if emission is not None:
        shader.inputs["Emission Color"].default_value = emission
        shader.inputs["Emission Strength"].default_value = 0.7
    return value


def box(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat: bpy.types.Material,
    *,
    bevel: float = 0.04,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new("Edge softness", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    obj.data.materials.append(mat)
    return obj


def sphere(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def line(
    name: str,
    points: list[tuple[float, float, float]],
    mat: bpy.types.Material,
    *,
    width: float = 0.018,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = width
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points, strict=True):
        point.co = (*coordinate, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def text(
    name: str,
    body: str,
    location: tuple[float, float, float],
    size: float,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.align_x = "LEFT"
    curve.size = size
    curve.extrude = 0.002
    curve.materials.append(mat)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (math.radians(76), 0, 0)
    return obj


def key_scale(obj: bpy.types.Object, start: int, end: int) -> None:
    final = obj.scale.copy()
    obj.scale = Vector((0.001, 0.001, 0.001))
    obj.keyframe_insert("scale", frame=start)
    obj.scale = final
    obj.keyframe_insert("scale", frame=end)


def look_at(obj: bpy.types.Object, point: tuple[float, float, float]) -> None:
    direction = Vector(point) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


reset_scene()

paper = material("Warm paper", (0.64, 0.61, 0.54, 1.0), roughness=0.86)
paper_light = material("Paper highlight", (0.82, 0.79, 0.71, 1.0), roughness=0.9)
studio = material("Warm studio", (0.52, 0.50, 0.46, 1.0), roughness=0.94)
ink = material("Ink", (0.025, 0.031, 0.043, 1.0), roughness=0.58)
graphite = material("Graphite", (0.25, 0.28, 0.33, 1.0), roughness=0.62)
line_gray = material("Document line", (0.58, 0.60, 0.64, 1.0), roughness=0.72)
review = material("Review amber", (0.62, 0.29, 0.055, 1.0), roughness=0.62)
cobalt = material(
    "Transformation blue",
    (0.035, 0.16, 0.82, 1.0),
    roughness=0.5,
    emission=(0.035, 0.16, 0.82, 1.0),
)
cyan = material(
    "Evidence cyan",
    (0.02, 0.55, 0.64, 1.0),
    roughness=0.48,
    emission=(0.02, 0.55, 0.64, 1.0),
)

documents: list[bpy.types.Object] = []
document_parts: list[bpy.types.Object] = []
semantic_blocks: list[bpy.types.Object] = []
evidence_paths: list[bpy.types.Object] = []
plane_parts: list[bpy.types.Object] = []
brand_parts: list[bpy.types.Object] = []

document_names = [
    "Annual Report",
    "Research Paper",
    "Technical Manual",
    "Contract",
    "Presentation",
    "Spreadsheet",
    "Scanned Archive",
    "Policy",
    "Dataset Dictionary",
    "Support Logs",
    "Public Filing",
    "Knowledge Notes",
]
initial_positions = [
    (-3.25, 1.15, 0.70),
    (-2.55, 0.62, 0.25),
    (-1.92, 1.35, 0.48),
    (-1.22, 0.42, 0.08),
    (-0.48, 1.05, 0.64),
    (0.18, 0.22, 0.18),
    (0.82, 1.22, 0.40),
    (1.55, 0.48, 0.04),
    (2.22, 1.12, 0.58),
    (2.86, 0.28, 0.16),
    (3.46, 1.04, 0.44),
    (3.96, 0.14, 0.02),
]
rotations = [
    (-4, 9, -7),
    (3, -10, 5),
    (-5, 7, 4),
    (2, -8, -6),
    (-3, 11, 6),
    (4, -6, -5),
    (-2, 8, -4),
    (5, -11, 5),
    (-4, 6, -6),
    (3, -9, 4),
    (-5, 10, 3),
    (2, -7, -4),
]
cover_materials = [
    ink,
    paper,
    graphite,
    paper_light,
    cobalt,
    paper,
    graphite,
    ink,
    paper_light,
    graphite,
    cobalt,
    paper,
]

for index, name in enumerate(document_names):
    root = bpy.data.objects.new(f"Document {index + 1:02d} {name}", None)
    bpy.context.collection.objects.link(root)
    root.location = initial_positions[index]
    root.rotation_euler = tuple(math.radians(v) for v in rotations[index])
    root.keyframe_insert("location", frame=1)
    root.keyframe_insert("rotation_euler", frame=1)

    width = 0.42 + (index % 4) * 0.055
    height = 1.34 + (index % 3) * 0.15
    depth = 0.16 + (index % 2) * 0.055
    body = box(f"{name} volume", (0, 0, 0), (width, depth, height * 0.5), paper, bevel=0.035)
    body.parent = root
    cover = box(
        f"{name} spine",
        (0, -depth - 0.026, 0),
        (width + 0.025, 0.022, height * 0.5 + 0.025),
        cover_materials[index],
        bevel=0.025,
    )
    cover.parent = root
    stripe = box(
        f"{name} semantic stripe",
        (0, -depth - 0.054, height * 0.16),
        (width * 0.66, 0.012, 0.035),
        cyan if index in (1, 5, 10) else line_gray,
        bevel=0.008,
    )
    stripe.parent = root
    for row in range(3):
        mark = box(
            f"{name} mark {row + 1}",
            (-width * 0.1, -depth - 0.054, height * (0.02 - row * 0.105)),
            (width * (0.58 - row * 0.07), 0.012, 0.018),
            paper_light if cover_materials[index] in (ink, graphite, cobalt) else ink,
            bevel=0.006,
        )
        mark.parent = root
        document_parts.append(mark)
    documents.append(root)
    document_parts.extend([body, cover, stripe])

    # Orientation: all spines face the viewer by 2 seconds.
    root.location.z += 0.12
    root.rotation_euler = (0, 0, 0)
    root.keyframe_insert("location", frame=25)
    root.keyframe_insert("rotation_euler", frame=25)

    # Semantic separation: rows open without losing their source identity.
    root.location.y += (index % 3 - 1) * 0.16
    root.location.z += 0.24 + (index % 2) * 0.08
    root.keyframe_insert("location", frame=48)

    # Alignment and compilation: a deterministic 4 x 3 knowledge plane.
    column = index % 4
    row = index // 4
    root.location = (-2.10 + column * 1.38, 0.42, 1.12 - row * 1.18)
    root.rotation_euler = (0, 0, 0)
    root.scale = (0.88, 0.36, 0.72)
    root.keyframe_insert("location", frame=83)
    root.keyframe_insert("rotation_euler", frame=83)
    root.keyframe_insert("scale", frame=83)
    root.location.y = 0.10 + (index % 3) * 0.018
    root.scale = (0.92, 0.22, 0.76)
    root.keyframe_insert("location", frame=102)
    root.keyframe_insert("scale", frame=102)

# A shallow substrate unifies accepted blocks while keeping material depth.
plane = box(
    "Knowledge Plane substrate", (0.0, 0.25, 0.0), (3.04, 0.06, 1.94), paper_light, bevel=0.10
)
plane_parts.append(plane)
key_scale(plane, 76, 98)

# Only a few measured-looking anchors receive evidence cyan; no global glow.
anchor_positions = [(-2.40, 0.00, 1.42), (-0.88, -0.02, 0.18), (1.76, 0.01, -1.02)]
for index, position in enumerate(anchor_positions):
    frame = box(f"Verified anchor {index + 1}", position, (0.34, 0.022, 0.16), cyan, bevel=0.012)
    semantic_blocks.append(frame)
    key_scale(frame, 55 + index * 4, 67 + index * 4)

evidence_specs = [
    [(-2.40, -0.05, 1.42), (-1.52, -0.18, 0.62), (-0.55, -0.05, 0.30)],
    [(-0.88, -0.05, 0.18), (0.18, -0.20, 0.56), (1.22, -0.05, 0.22)],
    [(1.76, -0.05, -1.02), (0.92, -0.18, -0.56), (0.15, -0.05, -0.42)],
]
for index, points in enumerate(evidence_specs):
    path = line(f"Evidence path {index + 1}", points, cyan, width=0.018)
    evidence_paths.append(path)
    key_scale(path, 60 + index * 4, 78 + index * 4)

# Two provisional candidates move to a clearly separated quarantine lane.
for index, z in enumerate((0.48, -0.38)):
    candidate = box(
        f"Quarantine candidate {index + 1}",
        (3.34, 0.02, z),
        (0.34, 0.035, 0.24),
        review,
        bevel=0.025,
    )
    semantic_blocks.append(candidate)
    key_scale(candidate, 58 + index * 5, 72 + index * 5)

# The Structara symbol is completed by negative space and two restrained paths.
symbol_points = [
    (-0.46, -0.09, 0.46),
    (0.46, -0.09, 0.46),
    (0.46, -0.09, -0.46),
    (-0.46, -0.09, -0.46),
    (-0.46, -0.09, 0.46),
]
symbol_outline = line("Structara negative-space outline", symbol_points, ink, width=0.028)
symbol_blue = line(
    "Structara transformation stroke",
    [(-0.26, -0.11, -0.12), (0.30, -0.11, 0.22)],
    cobalt,
    width=0.045,
)
symbol_cyan = line(
    "Structara evidence stroke", [(-0.18, -0.12, 0.22), (0.30, -0.12, -0.10)], cyan, width=0.032
)
brand_parts.extend([symbol_outline, symbol_blue, symbol_cyan])
for index, obj in enumerate(brand_parts):
    key_scale(obj, 100 + index * 3, 112 + index * 3)

text("Collection label", "12 SOURCES", (-3.10, 1.92, 0.02), 0.16, graphite)
text("Plane label", "VERIFIED KNOWLEDGE PLANE", (0.86, 1.92, 0.02), 0.16, graphite)
text(
    "Proof label",
    "PAGE  >  STRUCTURE  >  EVIDENCE  >  KNOWLEDGE",
    (-1.72, -2.12, 0.02),
    0.12,
    graphite,
)

# Floor and studio environment.
floor = box("Studio floor", (0.55, 0.0, -0.18), (36.0, 36.0, 0.04), studio, bevel=0.0)

world = bpy.context.scene.world
world.color = (0.52, 0.50, 0.46)
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.52, 0.50, 0.46, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.2

for name, light_type, location, energy, size in [
    ("Key", "AREA", (-3.0, -4.2, 6.5), 680, 5.0),
    ("Fill", "AREA", (4.5, -1.0, 4.0), 360, 4.0),
    ("Rim", "AREA", (1.0, 4.0, 5.5), 480, 3.0),
]:
    data = bpy.data.lights.new(name, light_type)
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, (0.4, 0.0, 0.0))

camera_data = bpy.data.cameras.new("Camera")
camera = bpy.data.objects.new("Camera", camera_data)
bpy.context.collection.objects.link(camera)
bpy.context.scene.camera = camera
camera.location = (0.20, -10.6, 6.7)
camera.data.lens = 56
look_at(camera, (0.15, 0.0, 0.08))

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.render.resolution_percentage = 100
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.view_settings.look = "AgX - Medium High Contrast"
scene.render.fps = 12
scene.frame_start = 1
scene.frame_end = 144

# All object actions use the same restrained ease; the sequence ends once.
for obj in bpy.context.scene.objects:
    action = obj.animation_data.action if obj.animation_data else None
    if not action:
        continue
    for fcurve in action.fcurves:
        for point in fcurve.keyframe_points:
            point.interpolation = "BEZIER"

scene.frame_set(144)
bpy.ops.wm.save_as_mainfile(filepath=str(MASTER_DIR / "hero-master.blend"))

# Full geometry and one-shot animation export.
export_objects = [
    *documents,
    *document_parts,
    *semantic_blocks,
    *evidence_paths,
    *plane_parts,
    *brand_parts,
]
bpy.ops.object.select_all(action="DESELECT")
for obj in export_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = documents[0]
bpy.ops.export_scene.gltf(
    filepath=str(DERIVATIVE_DIR / "hero-master.glb"),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_animations=True,
)

# LOD1 excludes thin document marks and keeps the same deterministic framing.
bpy.ops.object.select_all(action="DESELECT")
low_objects = [
    obj for obj in export_objects if " mark " not in obj.name and "label" not in obj.name.lower()
]
for obj in low_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = low_objects[0]
bpy.ops.export_scene.gltf(
    filepath=str(DERIVATIVE_DIR / "hero-master-low.glb"),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_animations=True,
)
shutil.copy2(DERIVATIVE_DIR / "hero-master.glb", PUBLIC_DIR / "hero-documents-master.glb")
shutil.copy2(DERIVATIVE_DIR / "hero-master-low.glb", PUBLIC_DIR / "hero-documents-tablet.glb")


def render_still(
    filename: str,
    width: int,
    height: int,
    *,
    camera_location: tuple[float, float, float] | None = None,
    transparent: bool = False,
) -> None:
    if camera_location is not None:
        camera.location = camera_location
        look_at(camera, (0.15, 0.0, 0.08))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = transparent
    scene.render.filepath = str(DERIVATIVE_DIR / filename)
    bpy.ops.render.render(write_still=True)


render_still("hero-poster-2880x1800.png", 2880, 1800)
render_still("hero-tablet-1600x1200.png", 1600, 1200, camera_location=(0.20, -11.3, 7.2))
render_still("hero-mobile-1080x1440.png", 1080, 1440, camera_location=(0.15, -12.8, 7.8))
render_still("hero-reduced-motion.png", 1200, 750, camera_location=(0.20, -10.6, 6.7))
render_still("hero-og-1200x630.png", 1200, 630, camera_location=(0.20, -11.2, 6.4))
render_still("hero-composition-a.png", 1200, 750, camera_location=(-0.35, -10.3, 6.9))
render_still("hero-composition-b.png", 1200, 750, camera_location=(0.80, -11.4, 6.3))
render_still("hero-composition-c.png", 1200, 750, camera_location=(-0.70, -10.8, 6.6))

# Transparent extraction objects for compositing and campaign derivatives.
all_renderables = [
    *document_parts,
    *semantic_blocks,
    *evidence_paths,
    *plane_parts,
    *brand_parts,
    floor,
]
transparent_groups = {
    "hero-object-source-pages-transparent.png": document_parts,
    "hero-object-evidence-blocks-transparent.png": [*semantic_blocks, *evidence_paths],
    "hero-object-knowledge-graph-transparent.png": [*plane_parts, *brand_parts],
}
camera.location = (0.20, -10.6, 6.7)
look_at(camera, (0.15, 0.0, 0.08))
for filename, visible in transparent_groups.items():
    visible_set = set(visible)
    for obj in all_renderables:
        obj.hide_render = obj not in visible_set
    render_still(filename, 1600, 1000, transparent=True)
for obj in all_renderables:
    obj.hide_render = False

# Return to the approved master camera before rendering motion.
camera.location = (0.20, -10.6, 6.7)
look_at(camera, (0.15, 0.0, 0.08))
scene.render.resolution_x = 960
scene.render.resolution_y = 600
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.ffmpeg.audio_codec = "NONE"
scene.render.filepath = str(DERIVATIVE_DIR / "hero-loop-12s.mp4")
bpy.ops.render.render(animation=True)

# Keep browser-served masters in one explicit, first-party namespace. AVIF and
# WebM transcodes are produced by the adjacent derivative script.
for output in DERIVATIVE_DIR.glob("hero-*.png"):
    shutil.copy2(output, PUBLIC_DIR / output.name)
for output in DERIVATIVE_DIR.glob("hero-*.mp4"):
    shutil.copy2(output, PUBLIC_DIR / output.name)

print("Structara hero master and derivatives created.")
