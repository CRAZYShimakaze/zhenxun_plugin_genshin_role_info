import asyncio
import copy

from ..utils.artifact_utils import (
    check_effective,
    get_artifact_score,
    get_effective,
    get_miao_score,
    get_upgrade_count_mark,
)
from ..utils.card_utils import json_path, role_score
from ..utils.image_utils import image_build
from ..utils.json_utils import load_json
from .damage.artifact_stats import static_two_piece_suits
from .damage.recommend import (
    apply_artifact_combination,
    artifact_slot_index,
    rank_single_artifacts,
    recommend_artifact_set,
    recommend_two_piece_damage,
    recommend_two_piece_sets,
)
from .draw_artifact_card import draw_artifact_card
from .draw_role_card import draw_role_card

avatar_url = "https://enka.network/ui/{}.png"
qq_logo_url = "http://q1.qlogo.cn/g?b=qq&nk={}&s=640"
role_info_json = load_json(f"{json_path}/role_info.json")

convert = {
    "main_prop": {
        "爆伤": "暴击伤害",
        "暴击": "暴击率",
        "精通": "元素精通",
        "生命": "百分比生命值",
        "防御": "百分比防御力",
        "攻击": "百分比攻击力",
        "火伤": "火元素伤害加成",
        "冰伤": "冰元素伤害加成",
        "雷伤": "雷元素伤害加成",
        "物伤": "物理伤害加成",
        "风伤": "风元素伤害加成",
        "水伤": "水元素伤害加成",
        "岩伤": "岩元素伤害加成",
        "草伤": "草元素伤害加成",
        "治疗": "治疗加成",
        "充能": "元素充能效率",
    },
    "suit_name": {
        "冰风": "冰风迷途的勇士",
        "角斗": "角斗士的终幕礼",
        "余响": "来歆余响",
        "磐岩": "悠古的磐岩",
        "饰金": "饰金之梦",
        "流星": "逆飞的流星",
        "辰砂": "辰砂往生录",
        "宗室": "昔日宗室之仪",
        "剧团": "黄金剧团",
        "逐影": "逐影猎人",
        "沉沦": "沉沦之心",
        "花海": "花海甘露之光",
        "绝缘": "绝缘之旗印",
        "谐律": "谐律异想断章",
        "乐园": "乐园遗落之花",
        "海染": "海染砗磲",
        "遐思": "未竟的遐思",
        "水仙": "水仙之梦",
        "少女": "被怜爱的少女",
        "追忆": "追忆之注连",
        "华馆": "华馆梦醒形骸记",
        "染血": "染血的骑士道",
        "回声": "回声之林夜话",
        "渡火": "渡过烈火的贤人",
        "昔时": "昔时之歌",
        "平雷": "平息鸣雷的尊者",
        "深林": "深林的记忆",
        "苍白": "苍白之火",
        "沙上": "沙上楼阁史话",
        "如雷": "如雷的盛怒",
        "千岩": "千岩牢固",
        "魔女": "炽烈的炎之魔女",
        "乐团": "流浪大地的乐团",
        "翠绿": "翠绿之影",
    },
}


def sort_recommend(artifact, position):
    artifact_recommend = []
    for role_name_full, effective in role_score.items():
        role_name = role_name_full.split("-")[0]
        role_info = role_info_json.get(role_name, {})
        if not role_info.get("元素"):
            continue
        affix_weight, point_mark, max_mark = get_miao_score(effective, role_info["属性"])
        artifact_score, grade, mark = get_artifact_score(
            point_mark,
            max_mark,
            artifact,
            role_info["元素"],
            position,
            role_name,
        )

        artifact_pk_info = {"角色": role_name, "元素": role_info["元素"]}
        # 旅行者按对应元素评分，头像仍使用空的通用资源。
        if role_name in {"风主", "岩主", "雷主", "草主", "水主", "火主", "冰主"}:
            artifact_pk_info["角色"] = "空"
        artifact_pk_info["星级"] = artifact["星级"]
        artifact_pk_info["图标"] = artifact["图标"]
        artifact_pk_info["图标链接"] = artifact.get("图标链接", "")
        artifact_pk_info["名称"] = role_name_full
        artifact_pk_info["评分"] = grade
        artifact_pk_info["评级"] = artifact_score
        artifact_pk_info["等级"] = artifact["等级"]
        artifact_pk_info["主属性"] = {"属性名": artifact["主属性"]["属性名"], "属性值": artifact["主属性"]["属性值"]}
        artifact_pk_info["副属性"] = []
        for j in range(len(artifact["词条"])):
            text = artifact["词条"][j]["属性名"].replace("百分比", "")
            up_num = get_upgrade_count_mark(mark[j])
            if artifact["词条"][j]["属性名"] not in ["攻击力", "防御力", "生命值", "元素精通"]:
                num = "+" + str(artifact["词条"][j]["属性值"]) + "%"
            else:
                num = "+" + str(artifact["词条"][j]["属性值"])
            artifact_pk_info["副属性"].append({"属性名": text, "属性值": num, "强化次数": up_num, "颜色": "white" if check_effective(artifact["词条"][j]["属性名"], effective) else "#afafaf"})
        artifact_recommend.append(copy.deepcopy(artifact_pk_info))
        if len(artifact_recommend) > 20:
            artifact_recommend = sorted(artifact_recommend, key=lambda x: float(x["评分"]), reverse=True)[:20]
    return artifact_recommend


async def gen_artifact_adapt(title, artifact, uid, role, pos, plugin_version):
    artifact_info = sort_recommend(artifact, pos)
    return await draw_artifact_card(title, role, uid, artifact_info, ace2_num=0, ace_num=0, plugin_version=plugin_version)


def _artifact_card_info(data, artifact, ori_artifact, role_name, pos):
    artifact_pk_info = {}
    if ori_artifact == artifact:
        artifact_pk_info["角色"] = role_name
    elif "角色" in artifact:
        artifact_pk_info["角色"] = artifact["角色"]
    effective, _ = get_effective(data)
    _, point_mark, max_mark = get_miao_score(
        effective,
        role_info_json[role_name]["属性"],
    )
    artifact_score, grade, mark = get_artifact_score(
        point_mark,
        max_mark,
        artifact,
        role_info_json[role_name]["元素"],
        pos,
        role_name,
    )
    artifact_pk_info["星级"] = artifact["星级"]
    artifact_pk_info["图标"] = artifact["图标"]
    artifact_pk_info["图标链接"] = artifact.get("图标链接", "")
    artifact_pk_info["名称"] = artifact["名称"]
    artifact_pk_info["评分"] = grade
    artifact_pk_info["评级"] = artifact_score
    artifact_pk_info["等级"] = artifact["等级"]
    artifact_pk_info["主属性"] = {
        "属性名": artifact["主属性"]["属性名"],
        "属性值": artifact["主属性"]["属性值"],
    }
    artifact_pk_info["副属性"] = []
    for index, affix in enumerate(artifact["词条"]):
        text = affix["属性名"].replace("百分比", "")
        up_num = get_upgrade_count_mark(mark[index])
        num = "+" + str(affix["属性值"])
        if affix["属性名"] not in ["攻击力", "防御力", "生命值", "元素精通"]:
            num += "%"
        artifact_pk_info["副属性"].append(
            {
                "属性名": text,
                "属性值": num,
                "强化次数": up_num,
                "颜色": (
                    "white"
                    if check_effective(affix["属性名"], effective)
                    else "#afafaf"
                ),
            }
        )
    return artifact_pk_info


async def gen_artifact_recommend(
    title,
    data,
    artifact_list,
    uid,
    role_name,
    pos,
    element,
    suit,
    plugin_version,
    damage_index=None,
    player_info=None,
):
    candidates = [
        artifact
        for artifact in artifact_list
        if convert["main_prop"].get(element, "")
        in artifact["主属性"]["属性名"]
        and suit in artifact["所属套装"]
    ]
    current = data["圣遗物"]
    slot_index = artifact_slot_index(current, pos)
    ori_artifact = current[slot_index] if slot_index < len(current) else None
    if damage_index is not None:
        recommendations = await asyncio.to_thread(
            rank_single_artifacts,
            data,
            candidates,
            pos,
            damage_index,
        )
        if not recommendations:
            return None, None
        artifact_all = []
        for recommendation in recommendations[:20]:
            artifact = recommendation.data["圣遗物"][slot_index]
            artifact_pk_info = _artifact_card_info(
                recommendation.data,
                artifact,
                ori_artifact,
                role_name,
                pos,
            )
            artifact_pk_info["伤害值"] = recommendation.value
            artifact_pk_info["评分"] = recommendation.value
            artifact_all.append(artifact_pk_info)
        img, _ = await draw_artifact_card(
            title,
            role_name,
            uid,
            artifact_all,
            ace2_num=0,
            ace_num=0,
            plugin_version=plugin_version,
        )
        return img, recommendations[0].title

    artifact_all = []

    for artifact in candidates:
        combination = [*current[:slot_index], artifact, *current[slot_index + 1:]]
        artifact_pk_info = _artifact_card_info(
            {**data, "圣遗物": combination},
            artifact,
            ori_artifact,
            role_name,
            pos,
        )
        if artifact_pk_info not in artifact_all:
            artifact_all.append(copy.deepcopy(artifact_pk_info))
        artifact_all = sorted(artifact_all, key=lambda x: float(x["评分"]), reverse=True)[: 20 if len(artifact_all) > 20 else len(artifact_all)]
    if not artifact_all:
        return None, None
    return await draw_artifact_card(title, role_name, uid, artifact_all, ace2_num=0, ace_num=0, plugin_version=plugin_version)


async def gen_attribute_set_recommend(
    title, data, player_info, uid, attribute, plugin_version, *, occupy=False, damage_index=None
):
    artifact_lists = player_info.data["圣遗物列表"]
    suits = static_two_piece_suits(convert["main_prop"][attribute])
    role_name = data["名称"]
    owner = role_name if occupy else None
    scoring = get_effective(data)
    _, point_mark, max_mark = get_miao_score(
        scoring[0].copy(), role_info_json[role_name]["属性"]
    )

    def score_artifact(position, artifact):
        _, score, _ = get_artifact_score(
            point_mark, max_mark, artifact, data["元素"], position, role_name
        )
        return score

    artifacts = await asyncio.to_thread(
        recommend_two_piece_sets, artifact_lists, suits, score_artifact, owner
    )
    target_title = None
    if damage_index is not None:
        recommendation = await asyncio.to_thread(
            recommend_two_piece_damage,
            data,
            artifact_lists,
            suits,
            damage_index,
            owner,
            score_combination=artifacts,
        )
        if recommendation is None:
            return None, None
        result = recommendation.data
        target_title = recommendation.title
        scoring = None
    else:
        if artifacts is None:
            return None, None
        result = apply_artifact_combination(data, artifacts)

    img, _ = await draw_role_card(
        uid, result, player_info, plugin_version, False, title, scoring=scoring
    )
    return image_build(img=img, quality=100, mode="RGB"), target_title


def _score_suit_combination(data, artifact_lists, role_name, suit, occupy):
    role_info = role_info_json[role_name]
    effective, _ = get_effective(data)
    _, point_mark, max_mark = get_miao_score(effective, role_info["属性"])
    best_by_position = []
    set_best_by_position = []

    for position, artifacts in enumerate(artifact_lists):
        best = None
        set_best = None
        for artifact in artifacts:
            if occupy and artifact.get("角色", "") not in {"", role_name}:
                continue
            _, score, _ = get_artifact_score(
                point_mark, max_mark, artifact, role_info["元素"], position, role_name
            )
            if best is None or score >= best[0]:
                best = (score, artifact)
            if suit in artifact["所属套装"] and (set_best is None or score >= set_best[0]):
                set_best = (score, artifact)
        best_by_position.append(best)
        set_best_by_position.append(set_best)

    best_score = None
    best_artifacts = None
    for off_piece, off_pick in enumerate(best_by_position):
        picks = list(set_best_by_position)
        picks[off_piece] = off_pick
        if any(pick is None for pick in picks):
            continue
        score = sum(pick[0] for pick in picks)
        if best_score is None or score > best_score:
            best_score = score
            best_artifacts = [pick[1] for pick in picks]
    return best_artifacts


async def gen_suit_recommend(
    title,
    data,
    player_info,
    uid,
    role_name,
    suit,
    occupy,
    plugin_version,
    damage_index=None,
):
    artifact_lists = player_info.data["圣遗物列表"]
    score_combination = _score_suit_combination(
        data, artifact_lists, role_name, suit, occupy
    )
    target_title = None
    if damage_index is not None:
        recommendation = await asyncio.to_thread(
            recommend_artifact_set,
            data,
            artifact_lists,
            suit,
            damage_index,
            occupy,
            score_combination=score_combination,
        )
        if recommendation is None:
            return None, None
        result = recommendation.data
        target_title = recommendation.title
    else:
        if score_combination is None:
            return None, None
        result = apply_artifact_combination(data, score_combination)

    img, _ = await draw_role_card(uid, result, player_info, plugin_version, False, title)
    return image_build(img=img, quality=100, mode="RGB"), target_title
