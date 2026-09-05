from pathlib import Path
p = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905\_parallel_omnidoc.py")
t = p.read_text(encoding="utf-8")
old = '''def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")'''
new = '''def yaml_path(path: Path) -> str:
    # Do NOT Path.resolve(): Windows junctions (md_<model> -> markdown) must keep
    # the md_<model> basename so OmniDoc save_name = md_<model>_quick_match (unique).
    # resolve() follows the junction and collapses every model onto markdown_quick_match,
    # clobbering the orphan deepseek run and sibling parallel scorers.
    return path.absolute().as_posix().replace("'", "''")'''
if old not in t:
    raise SystemExit("yaml_path block not found or already patched")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("PATCHED yaml_path")
# sanity
assert "path.absolute()" in p.read_text(encoding="utf-8")
assert 'path.resolve().as_posix()' not in p.read_text(encoding="utf-8")
