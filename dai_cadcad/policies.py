""" Policies Module

Contains the definition of the cadCAD system's policies.
Policies are typically broken down into `{{policy_name}}_all()` and `{{policy_name}}()` functions,
where the `_all()` is the actual "policy" function passed into the PSUBs, and the other is a helper
function.

The helper function typically contains the actual policy logic,
from the perspective of a single actor/action (executing the policy once).

The `_all()` typically orchestrates how many times the policy should execute, and with what options,
as well as checking the necessary conditions.
"""

from uuid import uuid4
from copy import deepcopy
import json
import random

from dai_cadcad import models
from dai_cadcad.pymaker.numeric import Wad, Ray, Rad


# ---


# Join


def gemjoin_join(vat, ilk_id, user_id, wad):
    """ Records a collateral deposit in the Vat.
    """

    assert wad >= Wad(0), "GemJoin/overflow"
    vat_slip(vat, ilk_id, user_id, wad)


def gemjoin_exit(vat, ilk_id, user_id, wad):
    """ Records a collateral withdrawal in the Vat.
    """

    assert wad <= Wad.from_number(2 ** 255), "GemJoin/overflow"
    vat_slip(vat, ilk_id, user_id, -wad)


def daijoin_join(vat, user_id, wad):
    """ Records an ERC-20 Dai deposit in the Vat.
    """

    vat_move(vat, "daijoin", user_id, wad)


def daijoin_exit(vat, user_id, wad):
    """ Records an ERC-20 Dai withdrawal in the Vat.
    """

    vat_move(vat, user_id, "daijoin", wad)


# ---


# Spotter


def spotter_peek(pip, timestep, init_timestep):
    """ Read in the price value at time `timestep` from feed `pip`.
    """

    with open(pip) as price_feed_json:
        return Wad.from_number(
            json.load(price_feed_json)[init_timestep + timestep]["price_close"]
        )


def spotter_poke(spotter, vat, ilk_id, now, init_timestep):
    """ Gets the current `spot` value of the given Ilk.
    """

    ilk = spotter["ilks"][ilk_id]
    val = spotter_peek(ilk["pip"], now, init_timestep)
    ilk["val"] = val

    if ilk_id not in ["dai", "gas"]:
        spot = Ray(val) / spotter["par"] / ilk["mat"]
        vat_file(vat, ilk_id, "spot", spot)


# ---


# Vat


def vat_file(vat, ilk_id, what, data):
    """ Sets the `what` field for the given Ilk to `data`.
    """

    if what == "spot":
        vat["ilks"][ilk_id]["spot"] = data
    elif what == "line":
        vat["ilks"][ilk_id]["line"] = data
    elif what == "dust":
        vat["ilks"][ilk_id]["dust"] = data


def vat_slip(vat, ilk_id, user_id, wad):
    """ Adds to the collateral record of the user. Creates the record if necessary.
    """

    gem = vat["gem"][ilk_id].get(user_id, Wad(0))
    gem += wad
    vat["gem"][ilk_id][user_id] = gem


def vat_flux(vat, ilk_id, src, dst, wad):
    """ Moves gem from one address to another. Assumes both addresses already exist.
    """

    vat["gem"][ilk_id][src] -= wad
    vat["gem"][ilk_id][dst] += wad


def vat_move(vat, src, dst, rad):
    """ Moves dai from one address to another. Assumes both addresses already exist.
    """

    vat["dai"][src] -= rad
    vat["dai"][dst] += rad


def vat_frob(vat, ilk_id, user_id, dink, dart):
    """ Sets an urn in the Vat and updates the collateral and Dai records approiately.

        Creates an urn and Dai record if they don't exist.
    """

    urn = deepcopy(vat["urns"][ilk_id].get(user_id, {"ink": Wad(0), "art": Wad(0)}))
    ilk = deepcopy(vat["ilks"][ilk_id])

    urn["ink"] += dink
    urn["art"] += dart
    ilk["Art"] += dart

    dtab = Rad(ilk["rate"] * dart)
    tab = Rad(ilk["rate"] * urn["art"])

    assert dart <= Wad(0) or (
        Rad(ilk["Art"] * ilk["rate"]) <= ilk["line"] and vat["debt"] <= vat["Line"]
    ), "Vat/ceiling-exceeded"
    assert (dart <= Wad(0) <= dink) or tab <= Rad(
        urn["ink"] * ilk["spot"]
    ), "Vat/not-safe"
    assert urn["art"] == Wad(0) or tab >= ilk["dust"], "Vat/dust"

    vat["debt"] += dtab
    vat["gem"][ilk_id][user_id] -= dink
    dai = vat["dai"].get(user_id, Rad(0))
    dai += dtab
    vat["dai"][user_id] = dai

    vat["urns"][ilk_id][user_id] = urn
    vat["ilks"][ilk_id] = ilk


def vat_grab(vat, ilk_id, user_id, dink, dart):
    """ Confiscates an urn.
    """

    urn = vat["urns"][ilk_id][user_id]
    ilk = vat["ilks"][ilk_id]

    urn["ink"] += dink
    urn["art"] += dart
    ilk["Art"] += dart

    dtab = Rad(ilk["rate"] * dart)

    vat["gem"][ilk_id]["cat"] -= dink
    vat["sin"]["vow"] -= dtab
    vat["vice"] -= dtab


# ---


# Vow


def vow_fess(vow, tab):
    """ Pushes to the debt queue.
    """

    vow["Sin"] += tab


# ---


# Cat


def cat_bite(vat, vow, cat, flipper, ilk_id, user_id, now):
    """ Liquidates an undercollateralized vault and puts its collateral up for a Flipper auction.
    """

    rate = vat["ilks"][ilk_id]["rate"]
    spot = vat["ilks"][ilk_id]["spot"]
    dust = vat["ilks"][ilk_id]["dust"]

    ink = vat["urns"][ilk_id][user_id]["ink"]
    art = vat["urns"][ilk_id][user_id]["art"]

    assert spot > Ray(0) and Rad(ink * spot) < Rad(art * rate), "Cat/not-unsafe"

    milk = cat["ilks"][ilk_id]
    room = cat["box"] - cat["litter"]

    assert cat["litter"] < cat["box"] and room >= dust, "Cat/liquidation-limit-hit"

    dart = Wad.min(art, Wad(Rad.min(milk["dunk"], room)) / Wad(rate) / milk["chop"])
    dink = Wad.min(ink, ink * dart / art)

    assert dart > Wad.from_number(0) and dink > Wad(0), "Cat/null-auction"
    assert dart <= Wad.from_number(2 ** 255) and dink <= Wad.from_number(
        2 ** 255
    ), "Cat/overflow"

    vat_grab(vat, ilk_id, user_id, Wad(0) - dink, Wad(0) - dart)
    vow_fess(vow, Rad(dart * rate))

    tab = Rad(dart * rate * milk["chop"])
    cat["litter"] += tab

    flipper_kick(flipper, vat, user_id, "vow", tab, dink, Rad(0), now + flipper["tau"])


def cat_claw(cat, rad):
    """ Subtracts from the measure of Dai up for liquidation.
    """

    cat["litter"] -= rad


# ---


# Flipper


def flipper_kick(flipper, vat, user_id, gal, tab, lot, bid, end):
    """ Kicks off a new Flip auction.
    """

    flipper["kicks"] += 1
    bid_id = flipper["kicks"]

    flipper["bids"][bid_id] = {
        "bid": bid,
        "lot": lot,
        "guy": "cat",
        "tic": 0,
        "end": end,
        "usr": user_id,
        "gal": gal,
        "tab": tab,
    }

    vat_flux(vat, flipper["ilk"], "cat", "flipper_eth", lot)


def flipper_tend(flipper, vat, bid_id, user_id, lot, bid, now):
    """ Places a tend bid on a Flipper auction.
    """

    curr_bid = flipper["bids"][bid_id]

    assert (
        curr_bid["tic"] > now or curr_bid["tic"] == 0
    ), "Flipper/already-finishied-tic"
    assert curr_bid["end"] > now, "Flipper/already-finishied-end"

    assert lot == curr_bid["lot"], "Flipper/lot-not-matching"
    assert bid <= curr_bid["tab"], "Flipper/higher-than-tab"
    assert bid > curr_bid["bid"], "Flipper/bid-not-higher"
    assert (
        bid >= curr_bid["bid"] * flipper["beg"] or bid == curr_bid["tab"]
    ), "Flipper/insufficient-increase"

    if user_id != curr_bid["guy"]:
        vat_move(vat, user_id, curr_bid["guy"], curr_bid["bid"])
        curr_bid["guy"] = user_id
    vat_move(vat, user_id, curr_bid["gal"], bid - curr_bid["bid"])

    curr_bid["bid"] = bid
    curr_bid["tic"] = now + flipper["ttl"]


def flipper_dent(flipper, vat, bid_id, user_id, lot, bid, now):
    """ Places a dent bid on a Flipper auction.
    """

    curr_bid = flipper["bids"][bid_id]

    assert curr_bid["tic"] > now or curr_bid["tic"] == 0, "Flipper/already-finished-tic"
    assert curr_bid["end"] > now, "Flipper/already-finished-end"

    assert bid == curr_bid["bid"], "Flipper/not-matching-bid"
    assert bid == curr_bid["tab"], "Flipper/tend-not-finished"
    assert lot < curr_bid["lot"], "Flipper/lot-not-lower"
    assert lot * flipper["beg"] <= curr_bid["lot"], "Flipper/insufficient-decrease"

    if user_id != curr_bid["guy"]:
        vat_move(vat, user_id, curr_bid["guy"], curr_bid["bid"])
        curr_bid["guy"] = user_id
    vat_flux(vat, flipper["ilk"], "flipper_eth", curr_bid["usr"], curr_bid["lot"] - lot)

    curr_bid["lot"] = lot
    curr_bid["tic"] = now + flipper["ttl"]


def flipper_deal(flipper, vat, cat, bid_id, now):
    """ Deals out a Flipper auction.
    """

    curr_bid = flipper["bids"][bid_id]

    assert curr_bid["tic"] != 0 and (
        curr_bid["tic"] <= now or curr_bid["end"] <= now
    ), "Flipper/not-finished"

    cat_claw(cat, curr_bid["tab"])
    vat_flux(vat, flipper["ilk"], "flipper_eth", curr_bid["guy"], curr_bid["lot"])
    del flipper["bids"][bid_id]


# ---


# Keepers / Users


def keeper_bid_flipper_eth(flipper, vat, spotter, stance, bid_id, user_id, now, stats):
    """ Executes a `keeper_bid`.
    """

    bid = flipper["bids"][bid_id]

    if stance and (
        "gas_price" not in stance
        or spotter["ilks"]["gas"]["val"] <= stance["gas_price"]
    ):
        price = stance["price"]

        if bid["bid"] == bid["tab"]:
            # Dent phase
            our_lot = Wad(bid["bid"] / Rad(price))
            if (
                our_lot * flipper["beg"] <= bid["lot"]
                and our_lot < bid["lot"]
                and vat["dai"][user_id] >= bid["bid"]
            ):
                flipper_dent(flipper, vat, bid_id, user_id, our_lot, bid["bid"], now)
                stats["num_bids"] += 1

        else:
            # Tend phase
            our_bid = Rad.min(Rad(bid["lot"]) * price, bid["tab"])
            if (
                (our_bid >= bid["bid"] * flipper["beg"] or our_bid == bid["tab"])
                and our_bid > bid["bid"]
                and vat["dai"][user_id]
                >= (our_bid if user_id != bid["guy"] else our_bid - bid["bid"])
            ):
                flipper_tend(flipper, vat, bid_id, user_id, bid["lot"], our_bid, now)
                stats["num_bids"] += 1


def open_eth_vault(vat, eth, dai):
    """ Opens a new vault with unjoined ETH collateral.
    """

    eth = Wad.from_number(eth)
    dai = Wad.from_number(dai)
    user_id = uuid4().hex
    gemjoin_join(vat, "eth", user_id, eth)
    vat_frob(vat, "eth", user_id, eth, dai)
    return user_id


# ---


# Generators / Top-Level Policies


def init(params, _substep, _state_hist, state):
    """ Injects simulation parameters into state, joins users into the system, and selectes a
        subset of them to be keepers.
    """

    now = state["timestep"]

    if now == 0:

        # Inject parameters into state

        new_cat = deepcopy(state["cat"])
        new_flapper = deepcopy(state["flapper"])
        new_flipper_eth = deepcopy(state["flipper_eth"])
        new_flopper = deepcopy(state["flopper"])
        new_spotter = deepcopy(state["spotter"])
        new_vat = deepcopy(state["vat"])
        new_vow = deepcopy(state["vow"])

        new_cat["box"] = params["CAT_BOX"]
        new_cat["ilks"]["eth"]["chop"] = params["CAT_ETH_CHOP"]
        new_cat["ilks"]["eth"]["dunk"] = params["CAT_ETH_DUNK"]
        new_flapper["beg"] = params["FLAPPER_BEG"]
        new_flapper["ttl"] = params["FLAPPER_TTL"]
        new_flapper["tau"] = params["FLAPPER_TAU"]
        new_flipper_eth["beg"] = params["FLIPPER_ETH_BEG"]
        new_flipper_eth["ttl"] = params["FLIPPER_ETH_TTL"]
        new_flipper_eth["tau"] = params["FLIPPER_ETH_TAU"]
        new_flopper["beg"] = params["FLOPPER_BEG"]
        new_flopper["pad"] = params["FLOPPER_PAD"]
        new_flopper["ttl"] = params["FLOPPER_TTL"]
        new_flopper["tau"] = params["FLOPPER_TAU"]
        new_spotter["par"] = params["SPOTTER_PAR"]
        new_spotter["ilks"]["eth"]["mat"] = params["SPOTTER_ETH_MAT"]
        new_spotter["ilks"]["eth"]["pip"] = params["SPOTTER_ETH_PIP"]
        new_spotter["ilks"]["dai"]["pip"] = params["SPOTTER_DAI_PIP"]
        new_spotter["ilks"]["gas"]["pip"] = params["SPOTTER_GAS_PIP"]
        new_vat["Line"] = params["VAT_LINE"]
        new_vat["ilks"]["eth"]["rate"] = params["VAT_ILK_ETH_RATE"]
        new_vat["ilks"]["eth"]["line"] = params["VAT_ILK_ETH_LINE"]
        new_vat["ilks"]["eth"]["dust"] = params["VAT_ILK_ETH_DUST"]
        new_vow["dump"] = params["VOW_DUMP"]
        new_vow["sump"] = params["VOW_SUMP"]
        new_vow["bump"] = params["VOW_BUMP"]
        new_vow["hump"] = params["VOW_HUMP"]

        # Remove dummy state objects

        new_keepers = deepcopy(state["keepers"])

        del new_flapper["bids"]["dummy_bid"]
        del new_flipper_eth["bids"]["dummy_bid"]
        del new_flopper["bids"]["dummy_bid"]
        del new_vat["urns"]["eth"]["dummy_urn"]
        del new_keepers["dummy_keeper"]

        # Join users into system
        # Warm-start the spotter for this

        init_timestep = params["INIT_TIMESTEP"]

        spotter_poke(new_spotter, new_vat, "eth", now, init_timestep)
        spotter_poke(new_spotter, new_vat, "dai", now, init_timestep)
        spotter_poke(new_spotter, new_vat, "gas", now, init_timestep)

        spot = float(new_vat["ilks"]["eth"]["spot"])
        rate = float(new_vat["ilks"]["eth"]["rate"])
        dust = float(new_vat["ilks"]["eth"]["dust"])

        for i in range(params["NUM_INIT_VAULTS"]):
            if i == 0:
                eth = 1000000
                dai = eth * spot * 0.9
                clever_boi = open_eth_vault(new_vat, eth, dai)
                nathan = open_eth_vault(new_vat, eth, dai)
            else:
                eth = random.uniform(1, 1000)
                dai = eth * spot * random.uniform(0.8, 1)
                if dai * rate > dust:
                    open_eth_vault(new_vat, eth, dai)

        # Select 10% at random to be basic auction keepers

        new_keepers[clever_boi] = {
            "flipper_eth_model": {"type": "clever_boi", "extra": {"discount": 0.15}},
            "flapper_model": {"type": "basic", "extra": {}},
            "flopper_model": {"type": "basic", "extra": {}},
        }
        new_keepers[nathan] = {
            "flipper_eth_model": {"type": "nathan_strategy", "extra": {}},
            "flapper_model": {"type": "basic", "extra": {}},
            "flopper_model": {"type": "basic", "extra": {}},
        }
        for user_id in random.sample(
            list(new_vat["urns"]["eth"].keys()),
            k=max(params["NUM_INIT_VAULTS"] // 10, 1),
        ):
            if user_id != clever_boi:
                new_keepers[user_id] = {
                    "flipper_eth_model": {
                        "type": "basic",
                        "extra": {
                            "gas_price": Wad.from_number(
                                random.uniform(15000000000, 50000000000)
                            ),
                            "discount": 0.15,
                        },
                    },
                    "flapper_model": {"type": "basic", "extra": {}},
                    "flopper_model": {"type": "basic", "extra": {}},
                }

        return {
            "vat": new_vat,
            "spotter": new_spotter,
            "cat": new_cat,
            "flapper": new_flapper,
            "flipper_eth": new_flipper_eth,
            "flopper": new_flopper,
            "vow": new_vow,
            "keepers": new_keepers,
        }

    return {}


def tick(params, _substep, _state_hist, state):
    """ Performs all expected, user-triggered system upkeep at the start of each timestep.
    """

    # TODO: Setting rates

    new_vat = deepcopy(state["vat"])
    new_spotter = deepcopy(state["spotter"])
    new_stats = deepcopy(state["stats"])

    now = state["timestep"]
    init_timestep = params["INIT_TIMESTEP"]

    spotter_poke(new_spotter, new_vat, "eth", now, init_timestep)
    spotter_poke(new_spotter, new_vat, "dai", now, init_timestep)
    spotter_poke(new_spotter, new_vat, "gas", now, init_timestep)

    new_stats["num_bids"] = 0
    new_stats["num_bites"] = 0

    return {"vat": new_vat, "spotter": new_spotter, "stats": new_stats}


def open_eth_vault_generator(_params, _substep, _state_hist, state):
    """ Executes all `open_eth_vault` policies for a timestep.
    """

    new_vat = deepcopy(state["vat"])
    dai_val = float(state["spotter"]["ilks"]["dai"]["val"])
    spot = float(new_vat["ilks"]["eth"]["spot"])
    rate = float(new_vat["ilks"]["eth"]["rate"])
    dust = float(new_vat["ilks"]["eth"]["dust"])

    if dai_val > 1:
        ddai_val = dai_val - 1
        prob = 5 * ddai_val + 0.05
        if random.random() <= prob:
            eth = random.uniform(1, 1000)
            dai = eth * spot * random.uniform(0.8, 1)
            if dai * rate > dust:
                open_eth_vault(new_vat, eth, dai)
                return {"vat": new_vat}

    return {}


def cat_bite_generator(_params, _substep, _state_hist, state):
    """ Executes all `bite` operations for a timestep.
    """

    new_vat = deepcopy(state["vat"])
    new_vow = deepcopy(state["vow"])
    new_cat = deepcopy(state["cat"])
    new_flipper_eth = deepcopy(state["flipper_eth"])
    new_stats = deepcopy(state["stats"])

    for user_id in new_vat["urns"]["eth"]:

        urn = new_vat["urns"]["eth"][user_id]
        ink = urn["ink"]
        art = urn["art"]

        ilk = new_vat["ilks"]["eth"]
        rate = ilk["rate"]
        spot = ilk["spot"]

        if Rad(ink * spot) < Rad(art * rate):
            cat_bite(
                new_vat,
                new_vow,
                new_cat,
                new_flipper_eth,
                "eth",
                user_id,
                state["timestep"],
            )
            new_stats["num_bites"] += 1

    return {
        "cat": new_cat,
        "flipper_eth": new_flipper_eth,
        "vat": new_vat,
        "vow": new_vow,
        "stats": new_stats,
    }


def keeper_bid_flipper_eth_generator(_params, _substep, _state_hist, state):
    """ Executes all `keeper_bid` policies for a timestep.
    """

    new_vat = deepcopy(state["vat"])
    spotter = state["spotter"]
    new_stats = deepcopy(state["stats"])
    keepers = state["keepers"]
    new_flipper_eth = deepcopy(state["flipper_eth"])
    bids = new_flipper_eth["bids"]
    now = state["timestep"]

    for bid_id in bids:
        bid = new_flipper_eth["bids"][bid_id]
        status = {
            "id": bid_id,
            "flipper": "flipper_eth",
            "bid": bid["bid"],
            "lot": bid["lot"],
            "tab": bid["tab"],
            "beg": new_flipper_eth["beg"],
            "guy": bid["guy"],
            "era": now,
            "tic": bid["tic"],
            "end": bid["end"],
            "price": Wad(bid["bid"] / Rad(bid["lot"]))
            if bid["lot"] != Wad(0)
            else None,
        }

        user_ids = list(keepers.keys())
        random.shuffle(user_ids)
        for user_id in user_ids:
            model_type = keepers[user_id]["flipper_eth_model"]["type"]
            model_extra = keepers[user_id]["flipper_eth_model"]["extra"]
            bidding_model = models.choose["flipper_eth"][model_type]

            stance = bidding_model(status, user_id, state, model_extra)

            keeper_bid_flipper_eth(
                new_flipper_eth,
                new_vat,
                spotter,
                stance,
                bid_id,
                user_id,
                now,
                new_stats,
            )

    return {"vat": new_vat, "flipper_eth": new_flipper_eth, "stats": new_stats}
#nathan's sorting algorithm. Sorts the auctions 
def nathan_keeper_bid_flipper_eth_generator(_params, _substep, _state_hist, state):
    """ Executes all `keeper_bid` policies for a timestep.
    """

    new_vat = deepcopy(state["vat"])
    spotter = state["spotter"]
    new_stats = deepcopy(state["stats"])
    keepers = state["keepers"]
    new_flipper_eth = deepcopy(state["flipper_eth"])
    bids = deepcopy(new_flipper_eth["bids"])
    now = state["timestep"]
    bids.sort(key = lambda bid:bid["lot"]/bid["bid"]*new_flipper_eth["beg"])
    for bid_id in bids:
        bid = new_flipper_eth["bids"][bid_id]
        status = {
            "id": bid_id,
            "flipper": "flipper_eth",
            "bid": bid["bid"],
            "lot": bid["lot"],
            "tab": bid["tab"],
            "beg": new_flipper_eth["beg"],
            "guy": bid["guy"],
            "era": now,
            "tic": bid["tic"],
            "end": bid["end"],
            "price": Wad(bid["bid"] / Rad(bid["lot"]))
            if bid["lot"] != Wad(0)
            else None,
        }
        
        #user_ids = list(keepers.keys())
        #random.shuffle(user_ids)
        #for user_id in user_ids:
        user_id = ""
        for i in list(keepers.keys()):
            if keepers[i]["flipper_eth_model"]["type"] == "nathan_strategy":
                user_id = i
        model_type = keepers[user_id]["flipper_eth_model"]["type"]
        model_extra = keepers[user_id]["flipper_eth_model"]["extra"]
        bidding_model = models.choose["flipper_eth"][model_type]

        stance = bidding_model(status, user_id, state, model_extra)

        keeper_bid_flipper_eth(
            new_flipper_eth,
            new_vat,
            spotter,
            stance,
            bid_id,
            user_id,
            now,
            new_stats,
            )

    return {"vat": new_vat, "flipper_eth": new_flipper_eth, "stats": new_stats}


def flipper_eth_deal_generator(_params, _substep, _state_hist, state):
    """ Scans for expired auctions and deals them out to the highest bidder.
    """

    new_vat = deepcopy(state["vat"])
    new_cat = deepcopy(state["cat"])
    new_flipper_eth = deepcopy(state["flipper_eth"])

    bids = new_flipper_eth["bids"]
    now = state["timestep"]

    bids_to_deal = []

    for bid_id in bids:
        if bids[bid_id]["tic"] != 0 and (
            bids[bid_id]["tic"] <= now or bids[bid_id]["end"] <= now
        ):
            bids_to_deal.append(bid_id)

    for bid_id in bids_to_deal:
        flipper_deal(new_flipper_eth, new_vat, new_cat, bid_id, now)

    return {
        "vat": new_vat,
        "cat": new_cat,
        "flipper_eth": new_flipper_eth,
    }


# ---
