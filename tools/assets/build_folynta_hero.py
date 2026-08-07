"""Build the first-party FOLYNTA Source-to-Knowledge hero master.

Run with Blender 4.5 LTS:
    blender --background --python tools/assets/build_folynta_hero.py

The scene intentionally uses only procedural geometry, Blender's bundled font,
and the approved FOLYNTA material palette. No external mesh, HDRI, texture,
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

paper = material("Paper", (0.72, 0.74, 0.77, 1.0), roughness=0.82)
paper_light = material("Paper light", (0.91, 0.90, 0.86, 1.0), roughness=0.86)
studio = material("Warm studio", (0.82, 0.81, 0.77, 1.0), roughness=0.92)
ink = material("Ink", (0.025, 0.031, 0.043, 1.0), roughness=0.5)
graphite = material("Graphite", (0.28, 0.31, 0.36, 1.0), roughness=0.45)
line_gray = material("Document line", (0.61, 0.63, 0.68, 1.0), roughness=0.65)
cobalt = material(
    "Cobalt",
    (0.035, 0.16, 0.82, 1.0),
    metallic=0.08,
    roughness=0.28,
    emission=(0.035, 0.16, 0.82, 1.0),
)
cyan = material(
    "Evidence cyan",
    (0.02, 0.55, 0.64, 1.0),
    metallic=0.04,
    roughness=0.3,
    emission=(0.02, 0.55, 0.64, 1.0),
)

pages: list[bpy.types.Object] = []
blocks: list[bpy.types.Object] = []
graph: list[bpy.types.Object] = []
edges: list[bpy.types.Object] = []

page_specs = [
    ((-2.15, 0.35, 0.30), (-0.09, 0.03, 0.02)),
    ((-1.72, 0.00, 0.16), (-0.03, -0.03, 0.01)),
    ((-1.28, -0.36, 0.02), (0.04, 0.02, -0.01)),
]
for index, (location, rotation) in enumerate(page_specs):
    page = box(f"Source page {index + 1}", location, (1.18, 1.55, 0.035), paper_light)
    page.rotation_euler = rotation
    pages.append(page)
    header = box(
        f"Page {index + 1} heading",
        (location[0] - 0.12, location[1] + 0.78, location[2] + 0.075),
        (0.72, 0.11, 0.018),
        ink,
        bevel=0.015,
    )
    header.rotation_euler = rotation
    pages.append(header)
    for row in range(4):
        content = box(
            f"Page {index + 1} line {row + 1}",
            (
                location[0] - 0.08,
                location[1] + 0.42 - row * 0.24,
                location[2] + 0.07,
            ),
            (0.76 - row * 0.06, 0.025, 0.012),
            line_gray,
            bevel=0.008,
        )
        content.rotation_euler = rotation
        pages.append(content)

block_specs = [
    ("Heading block", (-0.05, 0.78, 0.48), (0.86, 0.11, 0.055), ink),
    ("Paragraph block", (0.18, 0.40, 0.34), (1.03, 0.19, 0.05), paper),
    ("Formula block", (0.45, 0.03, 0.24), (0.68, 0.14, 0.05), paper),
    ("Figure block", (0.64, -0.50, 0.17), (0.82, 0.39, 0.05), paper_light),
    ("Caption block", (0.84, -0.94, 0.10), (0.62, 0.08, 0.04), graphite),
]
for name, location, scale, mat in block_specs:
    obj = box(name, location, scale, mat, bevel=0.025)
    blocks.append(obj)

figure_outline = [
    (-0.10, -0.78, 0.24),
    (1.38, -0.78, 0.24),
    (1.38, -0.22, 0.24),
    (-0.10, -0.22, 0.24),
    (-0.10, -0.78, 0.24),
]
blocks.append(line("Figure evidence frame", figure_outline, cyan, width=0.025))
blocks.append(line("Figure evidence diagonal A", [(-0.10, -0.78, 0.24), (1.38, -0.22, 0.24)], cyan))
blocks.append(line("Figure evidence diagonal B", [(-0.10, -0.22, 0.24), (1.38, -0.78, 0.24)], cyan))

node_positions = [
    (2.10, 0.80, 0.38),
    (2.72, 1.05, 0.57),
    (3.35, 0.72, 0.35),
    (3.70, 0.10, 0.48),
    (3.26, -0.42, 0.24),
    (2.61, -0.22, 0.14),
    (2.00, -0.58, 0.34),
    (1.67, -1.03, 0.18),
    (2.45, -1.12, 0.29),
    (3.16, -0.94, 0.45),
    (3.90, -0.72, 0.26),
    (4.18, 0.61, 0.15),
]
edge_pairs = [
    (0, 1),
    (0, 5),
    (1, 2),
    (2, 3),
    (2, 4),
    (3, 11),
    (4, 5),
    (4, 9),
    (5, 6),
    (6, 7),
    (6, 8),
    (7, 8),
    (8, 9),
    (9, 10),
    (3, 10),
    (0, 6),
]
for index, location in enumerate(node_positions):
    node = sphere(
        f"Knowledge node {index + 1}",
        location,
        0.14 if index not in (2, 3) else 0.21,
        cobalt if index in (2, 3, 9) else (cyan if index in (0, 5, 8) else graphite),
    )
    graph.append(node)
for index, (start, end) in enumerate(edge_pairs):
    edge = line(
        f"Knowledge edge {index + 1}",
        [node_positions[start], node_positions[end]],
        cyan if index in (0, 4, 8) else line_gray,
        width=0.012,
    )
    edges.append(edge)

text("Source label", "SOURCE PAGES", (-2.95, 1.88, 0.12), 0.18, graphite)
text("Graph label", "CONNECTED KNOWLEDGE", (2.05, 1.88, 0.12), 0.18, graphite)
text(
    "Proof label",
    "SOURCE  >  STRUCTURE  >  EVIDENCE  >  KNOWLEDGE",
    (-0.65, -1.74, 0.07),
    0.13,
    graphite,
)

# Floor and studio environment.
floor = box("Studio floor", (0.55, 0.0, -0.18), (36.0, 36.0, 0.04), studio, bevel=0.0)

world = bpy.context.scene.world
world.color = (0.82, 0.81, 0.77)
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.81, 0.77, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.28

for name, light_type, location, energy, size in [
    ("Key", "AREA", (-3.0, -4.2, 6.5), 1250, 5.0),
    ("Fill", "AREA", (4.5, -1.0, 4.0), 850, 4.0),
    ("Rim", "AREA", (1.0, 4.0, 5.5), 950, 3.0),
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
camera.location = (0.55, -8.8, 6.3)
camera.data.lens = 56
look_at(camera, (0.55, 0.0, 0.18))

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

# One explanatory 12-second motion: source, separation, proof, graph, resolve.
for obj in blocks:
    key_scale(obj, 34, 64)
for offset, obj in enumerate(edges):
    key_scale(obj, 72 + offset, 92 + offset)
for offset, obj in enumerate(graph):
    key_scale(obj, 82 + offset * 2, 104 + offset * 2)
for page_index, obj in enumerate(pages):
    if "Source page" not in obj.name:
        continue
    origin = obj.location.copy()
    obj.location.x += 0.32 * page_index
    obj.keyframe_insert("location", frame=1)
    obj.location = origin
    obj.keyframe_insert("location", frame=32)

for fcurve in (
    scene.animation_data.action.fcurves
    if scene.animation_data and scene.animation_data.action
    else []
):
    for point in fcurve.keyframe_points:
        point.interpolation = "BEZIER"

scene.frame_set(144)
bpy.ops.wm.save_as_mainfile(filepath=str(MASTER_DIR / "hero-master.blend"))

# Full geometry export.
bpy.ops.object.select_all(action="DESELECT")
for obj in [*pages, *blocks, *graph, *edges]:
    obj.select_set(True)
bpy.context.view_layer.objects.active = pages[0]
bpy.ops.export_scene.gltf(
    filepath=str(DERIVATIVE_DIR / "hero-master.glb"),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_animations=True,
)

# LOD1 excludes page typography, thin content lines, and half the graph edges.
bpy.ops.object.select_all(action="DESELECT")
low_objects = [
    obj
    for obj in [*pages, *blocks, *graph, *edges[::2]]
    if " line " not in obj.name and "label" not in obj.name.lower()
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
        look_at(camera, (0.55, 0.0, 0.18))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = transparent
    scene.render.filepath = str(DERIVATIVE_DIR / filename)
    bpy.ops.render.render(write_still=True)


render_still("hero-poster-2880x1800.png", 2880, 1800)
render_still("hero-tablet-1600x1200.png", 1600, 1200, camera_location=(0.45, -9.5, 6.9))
render_still("hero-mobile-1080x1440.png", 1080, 1440, camera_location=(0.50, -10.9, 7.4))
render_still("hero-reduced-motion.png", 1200, 750, camera_location=(0.55, -8.8, 6.3))
render_still("hero-og-1200x630.png", 1200, 630, camera_location=(0.55, -9.2, 6.0))
render_still("hero-composition-a.png", 1200, 750, camera_location=(0.20, -8.6, 6.5))
render_still("hero-composition-b.png", 1200, 750, camera_location=(1.10, -9.4, 5.8))
render_still("hero-composition-c.png", 1200, 750, camera_location=(-0.35, -9.0, 6.1))

# Transparent extraction objects for compositing and campaign derivatives.
all_renderables = [*pages, *blocks, *graph, *edges, floor]
transparent_groups = {
    "hero-object-source-pages-transparent.png": pages,
    "hero-object-evidence-blocks-transparent.png": blocks,
    "hero-object-knowledge-graph-transparent.png": [*graph, *edges],
}
camera.location = (0.55, -8.8, 6.3)
look_at(camera, (0.55, 0.0, 0.18))
for filename, visible in transparent_groups.items():
    visible_set = set(visible)
    for obj in all_renderables:
        obj.hide_render = obj not in visible_set
    render_still(filename, 1600, 1000, transparent=True)
for obj in all_renderables:
    obj.hide_render = False

# Return to the approved master camera before rendering motion.
camera.location = (0.55, -8.8, 6.3)
look_at(camera, (0.55, 0.0, 0.18))
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

print("FOLYNTA hero master and derivatives created.")
