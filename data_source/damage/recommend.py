from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import combinations, product
import math
from typing import Callable, Iterable

from .artifact_stats import (
    artifact_attributes as _artifact_attributes,
    static_set_attributes as _static_set_attributes,
)
from .engine import get_role_dmg

ELEMENT_INDEX = {
    "火": 1,
    "雷": 2,
    "水": 3,
    "草": 4,
    "风": 5,
    "岩": 6,
    "冰": 7,
}
MAX_EXHAUSTIVE_COMBINATIONS = 1_000
BEAM_WIDTH = 6
MAX_DAMAGE_FINALISTS = 4
GLOBAL_CANDIDATES = 10
MAX_SHORTLIST = 18


class DamageTargetError(ValueError):
    pass


@dataclass(frozen=True)
class DamageRecommendation:
    data: dict
    title: str
    value: float


def apply_artifact_combination(data: dict, artifacts: Iterable[dict]) -> dict:
    """Return role data adjusted from its current artifacts to ``artifacts``."""
    result = copy.deepcopy(data)
    selected = [copy.deepcopy(artifact) for artifact in artifacts]
    current = result.get("圣遗物", [])
    if len(selected) > 5:
        raise ValueError("候选圣遗物最多包含五个部位")

    delta: dict[str, float] = {}
    for sign, artifact_list in ((-1, current), (1, selected)):
        for artifact in artifact_list:
            for name, value in _artifact_attributes(artifact):
                delta[name] = delta.get(name, 0) + sign * value
        for name, value in _static_set_attributes(artifact_list):
            delta[name] = delta.get(name, 0) + sign * value

    prop = result["属性"]
    for stat, base_key, extra_key in (
        ("生命值", "基础生命", "额外生命"),
        ("攻击力", "基础攻击", "额外攻击"),
        ("防御力", "基础防御", "额外防御"),
    ):
        flat = delta.get(stat, 0)
        percent = delta.get(f"百分比{stat}", 0)
        prop[extra_key] = round(
            float(prop[extra_key]) + flat + float(prop[base_key]) * percent / 100
        )

    for stat, scale in (
        ("暴击率", 100),
        ("暴击伤害", 100),
        ("元素精通", 1),
        ("元素充能效率", 100),
        ("治疗加成", 100),
    ):
        prop[stat] = max(0, float(prop.get(stat, 0)) + delta.get(stat, 0) / scale)

    damage_bonus = list(prop.get("伤害加成", [0] * 8))
    damage_bonus.extend([0] * (8 - len(damage_bonus)))
    damage_bonus[0] += delta.get("物理伤害加成", 0) / 100
    for element, index in ELEMENT_INDEX.items():
        damage_bonus[index] += delta.get(f"{element}元素伤害加成", 0) / 100
    prop["伤害加成"] = damage_bonus
    result["圣遗物"] = selected
    return result


def get_damage_target(data: dict, damage_index: int) -> tuple[str, float]:
    rows = [
        (title, values)
        for title, values in (get_role_dmg(data) or {}).items()
        if title != "额外说明"
    ]
    if not rows:
        raise DamageTargetError("该角色暂无可用于推荐的伤害计算")
    if damage_index < 1 or damage_index > len(rows):
        raise DamageTargetError(
            f"伤害序号应在 1-{len(rows)} 之间，当前输入为 {damage_index}"
        )

    title, values = rows[damage_index - 1]
    return title, _damage_target_value(title, values, damage_index)


def _damage_target_value(title: str, values, damage_index: int) -> float:
    # Miao returns expected damage first even though the rendered table shows
    # the critical column on the left.
    if getattr(values, "is_text", False):
        raise DamageTargetError(f"第 {damage_index} 项“{title}”不是数值伤害")
    raw_value = values[0]
    try:
        return float(str(raw_value).rstrip("%"))
    except ValueError as error:
        raise DamageTargetError(f"第 {damage_index} 项“{title}”不是数值伤害") from error


def _evaluate(data: dict, artifacts: Iterable[dict], damage_index: int) -> DamageRecommendation:
    candidate_data = apply_artifact_combination(data, artifacts)
    title, value = get_damage_target(candidate_data, damage_index)
    return DamageRecommendation(candidate_data, title, value)


def artifact_slot_index(artifacts: list[dict], position: int) -> int:
    slot = ("生之花", "死之羽", "时之沙", "空之杯", "理之冠")[position]
    return next(
        (index for index, artifact in enumerate(artifacts) if artifact.get("部位") == slot),
        len(artifacts),
    )


def recommend_single_artifact(
    data: dict,
    artifacts: Iterable[dict],
    position: int,
    damage_index: int,
) -> DamageRecommendation | None:
    ranked = rank_single_artifacts(data, artifacts, position, damage_index)
    return ranked[0] if ranked else None


def rank_single_artifacts(
    data: dict,
    artifacts: Iterable[dict],
    position: int,
    damage_index: int,
) -> list[DamageRecommendation]:
    get_damage_target(data, damage_index)
    ranked: list[tuple[float, int, DamageRecommendation]] = []
    current = data["圣遗物"]
    slot_index = artifact_slot_index(current, position)
    for order, artifact in enumerate(artifacts):
        combination = [*current[:slot_index], artifact, *current[slot_index + 1:]]
        recommendation = _evaluate(data, combination, damage_index)
        ranked.append((recommendation.value, order, recommendation))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [recommendation for _, _, recommendation in ranked]


def _shortlist(ranked: list[dict]) -> list[dict]:
    selected = list(ranked[:GLOBAL_CANDIDATES])
    main_props = {
        artifact.get("主属性", {}).get("属性名")
        for artifact in selected
    }
    for artifact in ranked[GLOBAL_CANDIDATES:]:
        main_prop = artifact.get("主属性", {}).get("属性名")
        if main_prop not in main_props:
            selected.append(artifact)
            main_props.add(main_prop)
        if len(selected) >= MAX_SHORTLIST:
            break
    return selected


def _best_from_product(
    groups: list[list[dict]],
    evaluate: Callable[[Iterable[dict]], DamageRecommendation],
) -> DamageRecommendation | None:
    best: DamageRecommendation | None = None
    for combination in product(*groups):
        recommendation = evaluate(combination)
        if best is None or recommendation.value > best.value:
            best = recommendation
    return best


def _best_from_beam(
    groups: list[list[dict]],
    shortlists: list[list[dict]],
    evaluate: Callable[[Iterable[dict]], DamageRecommendation],
) -> DamageRecommendation | None:
    seed = [candidates[0] for candidates in shortlists]
    beam: list[tuple[float, list[dict], DamageRecommendation]] = []
    seed_result = evaluate(seed)
    beam.append((seed_result.value, seed, seed_result))

    # Expanding the largest group first avoids paying its branching factor
    # once for every item already retained in the beam.
    for position in sorted(range(5), key=lambda index: len(shortlists[index]), reverse=True):
        expanded: list[tuple[float, list[dict], DamageRecommendation]] = []
        for _, combination, _ in beam:
            for artifact in shortlists[position]:
                next_combination = list(combination)
                next_combination[position] = artifact
                recommendation = evaluate(next_combination)
                expanded.append((recommendation.value, next_combination, recommendation))
        expanded.sort(key=lambda item: item[0], reverse=True)
        beam = expanded[:BEAM_WIDTH]

    best = beam[0][2] if beam else None
    if best is None:
        return None

    # Revisit every cached artifact while holding the other four fixed. This
    # recovers strong candidates omitted by the shortlist without an unbounded
    # five-dimensional Cartesian product.
    combination = list(best.data["圣遗物"])
    for position, candidates in enumerate(groups):
        position_best = best
        for artifact in candidates:
            next_combination = list(combination)
            next_combination[position] = artifact
            recommendation = evaluate(next_combination)
            if recommendation.value > position_best.value:
                position_best = recommendation
        if position_best.value > best.value:
            best = position_best
            combination = list(best.data["圣遗物"])
    return best


def _two_piece_groups(
    artifact_lists: Iterable[Iterable[dict]],
    suits: set[str],
    owner: str | None,
) -> list[dict[str | None, list[dict]]]:
    groups = []
    for artifacts in artifact_lists:
        by_suit: dict[str | None, list[dict]] = {}
        for artifact in artifacts:
            if artifact.get("星级") not in (5, "5"):
                continue
            if owner is not None and artifact.get("角色", "") not in {"", owner}:
                continue
            by_suit.setdefault(None, []).append(artifact)
            suit = artifact.get("所属套装")
            if suit in suits:
                by_suit.setdefault(suit, []).append(artifact)
        groups.append(by_suit)
    return groups


def _two_piece_layouts(
    groups: list[dict[str | None, list[dict]]],
) -> Iterable[tuple[str | None, ...]]:
    positions = range(5)
    if len(groups) != len(positions) or not all(groups):
        return
    available_suits = sorted({suit for group in groups for suit in group if suit is not None})
    for first, second in combinations(available_suits, 2):
        for off_piece in positions:
            set_positions = [position for position in positions if position != off_piece]
            for first_positions in combinations(set_positions, 2):
                layout: list[str | None] = [second] * len(positions)
                layout[off_piece] = None
                for position in first_positions:
                    layout[position] = first
                if all(suit in group for group, suit in zip(groups, layout)):
                    yield tuple(layout)


def recommend_two_piece_sets(
    artifact_lists: Iterable[Iterable[dict]],
    suits: set[str],
    score_artifact: Callable[[int, dict], float],
    owner: str | None = None,
) -> list[dict] | None:
    groups = _two_piece_groups(artifact_lists, suits, owner)
    layouts = list(_two_piece_layouts(groups))
    if not layouts:
        return None

    best_by_position = []
    for position, by_suit in enumerate(groups):
        scored = {
            id(artifact): (score_artifact(position, artifact), artifact)
            for artifact in by_suit[None]
        }
        best_by_position.append({
            suit: max((scored[id(artifact)] for artifact in candidates), key=lambda pick: pick[0])
            for suit, candidates in by_suit.items()
        })

    best_score = -math.inf
    best_artifacts = None
    for layout in layouts:
        picks = [best[suit] for best, suit in zip(best_by_position, layout)]
        score = sum(pick[0] for pick in picks)
        if score > best_score:
            best_score = score
            best_artifacts = [pick[1] for pick in picks]
    return best_artifacts


def recommend_two_piece_damage(
    data: dict,
    artifact_lists: Iterable[Iterable[dict]],
    suits: set[str],
    damage_index: int,
    owner: str | None = None,
    *,
    score_combination: list[dict] | None = None,
) -> DamageRecommendation | None:
    groups = _two_piece_groups(artifact_lists, suits, owner)
    layout_groups = [
        [group[suit] for group, suit in zip(groups, layout)]
        for layout in _two_piece_layouts(groups)
    ]
    return _search_damage_layouts(
        data, layout_groups, damage_index, score_combination=score_combination
    )


def _search_damage_layouts(
    data: dict,
    layout_groups: list[list[list[dict]]],
    damage_index: int,
    *,
    score_combination: list[dict] | None = None,
) -> DamageRecommendation | None:
    title, _ = get_damage_target(data, damage_index)
    if not layout_groups:
        return None

    def evaluate(artifacts: Iterable[dict]) -> DamageRecommendation:
        candidate = apply_artifact_combination(data, artifacts)
        damage = get_role_dmg(candidate) or {}
        values = damage.get(title)
        value = -math.inf
        if values is not None:
            try:
                value = _damage_target_value(title, values, damage_index)
            except DamageTargetError:
                pass
        return DamageRecommendation(candidate, title, value)

    total = sum(math.prod(map(len, candidates)) for candidates in layout_groups)
    best = evaluate(score_combination) if score_combination is not None else None
    if total <= MAX_EXHAUSTIVE_COMBINATIONS:
        for candidates in layout_groups:
            result = _best_from_product(candidates, evaluate)
            if result is not None and (best is None or result.value > best.value):
                best = result
    else:
        # Rank each piece once, evaluate a full build for every valid layout,
        # and run the existing beam search on the highest-damage layouts.
        reference = list(data.get("圣遗物", []))
        if len(reference) != 5:
            reference = [candidates[0] for candidates in layout_groups[0]]
        shortlists_by_position = []
        for position, position_groups in enumerate(zip(*layout_groups)):
            unique_groups = {id(group): group for group in position_groups}
            artifacts = {
                id(artifact): artifact
                for group in unique_groups.values()
                for artifact in group
            }
            values = {
                key: evaluate(
                    [*reference[:position], artifact, *reference[position + 1:]]
                ).value
                for key, artifact in artifacts.items()
            }
            shortlists_by_position.append({
                key: _shortlist(sorted(
                    group, key=lambda artifact: values[id(artifact)], reverse=True
                ))
                for key, group in unique_groups.items()
            })

        finalists = []
        for candidates in layout_groups:
            shortlists = [
                by_group[id(group)] for by_group, group in zip(shortlists_by_position, candidates)
            ]
            result = evaluate([shortlist[0] for shortlist in shortlists])
            finalists.append((result.value, candidates, shortlists))
            if best is None or result.value > best.value:
                best = result
        finalists.sort(key=lambda item: item[0], reverse=True)
        for _, candidates, shortlists in finalists[:MAX_DAMAGE_FINALISTS]:
            result = _best_from_beam(candidates, shortlists, evaluate)
            if result is not None and (best is None or result.value > best.value):
                best = result

    return best if best is not None and best.value > -math.inf else None


def recommend_artifact_set(
    data: dict,
    artifact_lists: Iterable[Iterable[dict]],
    suit: str,
    damage_index: int,
    occupy: bool = False,
    *,
    score_combination: list[dict] | None = None,
) -> DamageRecommendation | None:
    role_name = data["名称"]
    all_groups = [
        [
            artifact
            for artifact in artifacts
            if not occupy or artifact.get("角色", "") in {"", role_name}
        ]
        for artifacts in artifact_lists
    ]
    suit_groups = [
        [artifact for artifact in artifacts if suit in artifact.get("所属套装", "")]
        for artifacts in all_groups
    ]
    layout_groups = []
    for off_piece in range(5):
        groups = [
            all_groups[position] if position == off_piece else suit_groups[position]
            for position in range(5)
        ]
        if all(groups):
            layout_groups.append(groups)
    return _search_damage_layouts(
        data, layout_groups, damage_index, score_combination=score_combination
    )
