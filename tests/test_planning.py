from pathlib import Path


def F(path, root, *, mtime=0, top=None, size=10):
    from app.planning.engine import CandidateFile
    p = Path(path)
    return CandidateFile(
        path=p,
        root_id=root,
        top_level_dir=top or str(p.parent),
        size=size,
        mtime_ns=mtime,
        device=root,
        inode=abs(hash(str(p))) % 100000 + 1,
    )


def G(h, *files):
    from app.planning.engine import CandidateGroup
    return CandidateGroup(content_hash=h, file_size=files[0].size, files=tuple(files))


def test_keep_first_root_prefers_earlier_root():
    from app.planning.engine import generate_plan
    groups = [G("h", F("/A/x", 0), F("/B/x", 1))]
    plan = generate_plan(groups, policy="keep-first-root", root_order=[0, 1])
    assert str(plan.items[0].keep.path) == "/A/x"
    assert str(plan.items[0].delete.path) == "/B/x"


def test_keep_newest_and_oldest():
    from app.planning.engine import generate_plan
    group = G("h", F("/A/x", 0, mtime=10), F("/B/x", 1, mtime=20))
    newest = generate_plan([group], policy="keep-newest", root_order=[0, 1])
    oldest = generate_plan([group], policy="keep-oldest", root_order=[0, 1])
    assert newest.items[0].keep.mtime_ns == 20
    assert oldest.items[0].keep.mtime_ns == 10


def test_balanced_roots_alternates_equal_pairs():
    from app.planning.engine import generate_plan
    groups = [G(f"h{i}", F(f"/A/{i}", 0), F(f"/B/{i}", 1)) for i in range(8)]
    plan = generate_plan(groups, policy="balanced-roots", root_order=[0, 1])
    assert plan.delete_counts == {0: 4, 1: 4}


def test_balanced_roots_handles_odd_pairs_with_difference_at_most_one():
    from app.planning.engine import generate_plan
    groups = [G(f"h{i}", F(f"/A/{i}", 0), F(f"/B/{i}", 1)) for i in range(7)]
    plan = generate_plan(groups, policy="balanced-roots", root_order=[0, 1])
    assert abs(plan.delete_counts.get(0, 0) - plan.delete_counts.get(1, 0)) <= 1


def test_group_with_three_members_keeps_one_and_deletes_two():
    from app.planning.engine import generate_plan
    group = G("h", F("/A/x", 0), F("/B/x", 1), F("/B/y", 1))
    plan = generate_plan([group], policy="keep-first-root", root_order=[0, 1])
    assert len(plan.items) == 2
    assert {str(i.delete.path) for i in plan.items} == {"/B/x", "/B/y"}


def test_protected_directory_never_schedules_last_file():
    from app.planning.engine import generate_plan
    group = G(
        "h",
        F("/A/only.jpg", 0, top="/A/top"),
        F("/B/copy.jpg", 1, top="/B/top"),
    )
    plan = generate_plan(
        [group],
        policy="balanced-roots",
        root_order=[0, 1],
        directory_file_counts={"/A/top": 1, "/B/top": 10},
        protect_last_file=True,
    )
    assert str(plan.items[0].keep.path) == "/A/only.jpg"
    assert str(plan.items[0].delete.path) == "/B/copy.jpg"


def test_path_priority_prefers_first_matching_pattern():
    from app.planning.engine import generate_plan
    group = G("h", F("/data/raw/x.jpg", 0), F("/data/curated/x.jpg", 1))
    plan = generate_plan(
        [group],
        policy="path-priority",
        root_order=[0, 1],
        path_priority_patterns=["*/curated/*", "*/raw/*"],
    )
    assert str(plan.items[0].keep.path) == "/data/curated/x.jpg"


def test_relative_path_preference_uses_candidate_relative_path():
    from app.planning.engine import CandidateFile, generate_plan
    a = CandidateFile(Path("/A/one.jpg"), 0, "/A", 10, 1, 1, 1, relative_path="preferred/one.jpg")
    b = CandidateFile(Path("/B/one.jpg"), 1, "/B", 10, 1, 2, 2, relative_path="archive/preferred/one.jpg")
    plan = generate_plan(
        [G("h", a, b)],
        policy="relative-path-preference",
        root_order=[0, 1],
        relative_path_priority_patterns=["preferred/*", "archive/*"],
    )
    assert plan.items[0].keep == a
