# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Readable names for fields whose own names are not.

An appliance calls its fields whatever it calls them, and the entities are
named from that, which gives "User selections analog spin speed" for the spin
speed. The ones worth naming properly are named here and the rest keep what
can be worked out from the name, so an appliance nobody has seen still gets
entities with names on them.

A name here is looked up by the field alone, without the group it sits in or
any model code in front of it, so one entry covers a field wherever it turns up
and whichever model spells it with a prefix of its own.

The platforms each named field is known to appear on are worked out by
tools/make_names.py from every capability tree to hand, and the block at the
bottom is its doing. A name is only used where Home Assistant has been given
the text for it, which is what that block records.
"""

from __future__ import annotations

import re

# A model code stuck on the front of a field name, as in EWX1493A_easyIron.
MODEL_PREFIX = re.compile(r"^[A-Z]{2,}[0-9A-Z]*_")

# Where one word ends and the next begins in a name written in camel case, as
# at the T of analogTemperature.
CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")

NAMES: dict[str, str] = {
    # What the appliance is doing
    "applianceState": "State",
    "applianceMode": "Mode",
    "cyclePhase": "Cycle phase",
    "cycleSubPhase": "Cycle step",
    "actionState": "Action",
    "reason": "Reason",
    "errorCode": "Error code",
    "remoteControl": "Remote control",
    "remoteNotificationPending": "Remote notifications",
    "connectivityState": "Connectivity",
    # Doors, locks and lids
    "doorState": "Door",
    "doorLock": "Door lock",
    "childLock": "Child lock",
    "uiLock": "Panel lock",
    "uiLocked": "Panel lock",
    "uiLockMode": "Panel lock",
    # A wash
    "programUID": "Programme",
    "program": "Programme",
    "analogTemperature": "Temperature",
    "analogSpinSpeed": "Spin speed",
    "extraRinseNumber": "Extra rinse",
    "defaultExtraRinse": "Extra rinse by default",
    "rinse": "Rinse",
    "rinseHold": "Rinse hold",
    "steamValue": "Steam",
    "stain": "Stain",
    "preWashPhase": "Prewash",
    "nightCycle": "Night cycle",
    "anticreaseNoSteam": "Crease guard",
    "anticreaseWSteam": "Crease guard with steam",
    "easyIron": "Easy iron",
    "wmEconomy": "Economy",
    "intensive": "Intensive",
    "ultraMix": "Ultra mix",
    "dryMode": "Drying",
    "wetMode": "Wet",
    "tcSensor": "Load sensing",
    "timeManagerLevel": "Time manager",
    "phaseAdvance": "Skip phase",
    "washLevel": "Wash level",
    "turboAgitation": "Turbo agitation",
    "turboDrying": "Turbo drying",
    "waterReuse": "Water reuse",
    "detergentType": "Detergent",
    "memoryId": "Saved cycle",
    "washingNominalLoadWeight": "Nominal load",
    "fcOptisenseLoadWeight": "Measured load",
    "waterLevel": "Water level",
    "waterHardness": "Water hardness",
    "waterSoftenerMode": "Water softener",
    # Times
    "timeToEnd": "Time to end",
    "runningTime": "Running time",
    "startTime": "Start in",
    "stopTime": "Finish in",
    "minFinishInTime": "Shortest finish in",
    "totalWashingTime": "Total washing time",
    "applianceTotalWorkingTime": "Total working time",
    "totalRuntime": "Total running time",
    "cleanTime": "Cleaning time",
    "airDryDuration": "Air drying time",
    # Counters
    "totalCycleCounter": "Cycles run",
    "totalWashCyclesCount": "Washes run",
    "cleanedArea": "Area cleaned",
    "cleanRepetitions": "Passes",
    # Sound, light and language
    "endOfCycleSound": "End of cycle sound",
    "soundVolume": "Volume",
    "alertSoundsEnabled": "Alert sounds",
    "displayLight": "Display brightness",
    "language": "Language",
    "voiceLanguage": "Voice language",
    "doNotDisturbEnabled": "Do not disturb",
    "doNotDisturbStartTime": "Do not disturb from",
    "doNotDisturbEndTime": "Do not disturb until",
    # Heat and air
    "targetTemperature": "Target temperature",
    "targetTemperatureC": "Target temperature",
    "ambientTemperatureC": "Room temperature",
    "ambientTemperatureF": "Room temperature",
    "temperature": "Temperature",
    "targetFoodProbeTemperatureC": "Food probe target",
    "foodProbeInsertionState": "Food probe",
    "fanMode": "Fan mode",
    "fanSpeed": "Fan speed",
    "fanSpeedSetting": "Fan speed",
    "fanSpeedState": "Fan speed",
    "flapPosition": "Louvre position",
    "flapOscillate": "Louvre swing",
    "verticalSwing": "Vertical swing",
    "sleepMode": "Sleep mode",
    "energySavingMode": "Energy saving",
    "comfortAir": "Comfort air",
    "cleanAirMode": "Clean air",
    "airQualityLight": "Air quality light",
    "filterState": "Filter",
    "lifeRemaining": "Life remaining",
    "pm25Approximate": "PM2.5",
    "iFeel": "I Feel",
    "iClean": "I Clean",
    "xFan": "X Fan",
    "waterTankEmpty": "Water tank empty",
    "waterTrayInsertionState": "Water tray",
    "evaporatorDefrostState": "Defrosting",
    # Cleaning
    "batteryLevel": "Battery",
    "chargeState": "Charging",
    "chargeBreak": "Charge break",
    "cleaningMode": "Cleaning mode",
    "cleaningPhase": "Cleaning phase",
    "cleaningType": "Cleaning type",
    "vacuumPower": "Suction",
    "mopWaterRate": "Water flow",
    "mopAttachState": "Mop attached",
    "mopLocation": "Mop",
    "moppingPattern": "Mopping pattern",
    "brushRuntime": "Brush runtime",
    "sideBrushRuntime": "Side brush runtime",
    "mopRuntime": "Mop runtime",
    "carpetTurbo": "Carpet boost",
    "edgeCleanActive": "Edge cleaning",
    "petAvoidance": "Avoid pets",
    "avoidCollision": "Avoid obstacles",
    # The machine itself
    "applianceMainBoardSwVersion": "Board firmware",
    "applianceUiSwVersion": "Panel firmware",
    "swUpdateState": "Update state",
    "model": "Model",
    "nickname": "Name",
    "alerts": "Alerts",
}


def readable(field: str) -> str | None:
    """The name for a field, if it has one worth using."""
    return NAMES.get(MODEL_PREFIX.sub("", field))


def key_for(field: str) -> str:
    """What Home Assistant looks the text up under."""
    plain = MODEL_PREFIX.sub("", field)
    return CAMEL.sub(r"_\1", plain).lower()


# Everything below is written by tools/make_names.py. Do not edit it by hand.
PLATFORMS_FOR: dict[str, frozenset[str]] = {
    "action_state": frozenset({"sensor"}),
    "air_dry_duration": frozenset({"sensor"}),
    "air_quality_light": frozenset({"select"}),
    "alert_sounds_enabled": frozenset({"switch"}),
    "alerts": frozenset({"binary_sensor", "sensor"}),
    "ambient_temperature_c": frozenset({"sensor"}),
    "ambient_temperature_f": frozenset({"sensor"}),
    "analog_spin_speed": frozenset({"select"}),
    "analog_temperature": frozenset({"select"}),
    "anticrease_no_steam": frozenset({"switch"}),
    "anticrease_wsteam": frozenset({"switch"}),
    "appliance_main_board_sw_version": frozenset({"sensor"}),
    "appliance_mode": frozenset({"select"}),
    "appliance_state": frozenset({"sensor"}),
    "appliance_total_working_time": frozenset({"sensor"}),
    "appliance_ui_sw_version": frozenset({"sensor"}),
    "avoid_collision": frozenset({"switch"}),
    "battery_level": frozenset({"sensor"}),
    "brush_runtime": frozenset({"sensor"}),
    "carpet_turbo": frozenset({"switch"}),
    "charge_break": frozenset({"binary_sensor"}),
    "charge_state": frozenset({"binary_sensor"}),
    "child_lock": frozenset({"switch"}),
    "clean_air_mode": frozenset({"select", "sensor"}),
    "clean_repetitions": frozenset({"sensor"}),
    "clean_time": frozenset({"sensor"}),
    "cleaned_area": frozenset({"sensor"}),
    "cleaning_mode": frozenset({"select"}),
    "cleaning_phase": frozenset({"sensor"}),
    "cleaning_type": frozenset({"sensor"}),
    "comfort_air": frozenset({"select"}),
    "connectivity_state": frozenset({"sensor"}),
    "cycle_phase": frozenset({"sensor"}),
    "cycle_sub_phase": frozenset({"sensor"}),
    "default_extra_rinse": frozenset({"select"}),
    "detergent_type": frozenset({"select"}),
    "display_light": frozenset({"number", "select"}),
    "do_not_disturb_enabled": frozenset({"switch"}),
    "do_not_disturb_end_time": frozenset({"sensor"}),
    "do_not_disturb_start_time": frozenset({"sensor"}),
    "door_lock": frozenset({"sensor"}),
    "door_state": frozenset({"sensor"}),
    "edge_clean_active": frozenset({"switch"}),
    "end_of_cycle_sound": frozenset({"select"}),
    "energy_saving_mode": frozenset({"select"}),
    "error_code": frozenset({"sensor"}),
    "evaporator_defrost_state": frozenset({"sensor"}),
    "extra_rinse_number": frozenset({"select"}),
    "fan_mode": frozenset({"select"}),
    "fan_speed": frozenset({"sensor"}),
    "fan_speed_setting": frozenset({"select"}),
    "fan_speed_state": frozenset({"sensor"}),
    "fc_optisense_load_weight": frozenset({"sensor"}),
    "filter_state": frozenset({"sensor"}),
    "flap_oscillate": frozenset({"select"}),
    "flap_position": frozenset({"number", "select"}),
    "food_probe_insertion_state": frozenset({"sensor"}),
    "i_clean": frozenset({"select"}),
    "i_feel": frozenset({"sensor"}),
    "language": frozenset({"sensor"}),
    "life_remaining": frozenset({"sensor"}),
    "memory_id": frozenset({"select"}),
    "min_finish_in_time": frozenset({"sensor"}),
    "model": frozenset({"sensor"}),
    "mop_attach_state": frozenset({"binary_sensor"}),
    "mop_location": frozenset({"sensor"}),
    "mop_runtime": frozenset({"sensor"}),
    "mop_water_rate": frozenset({"select"}),
    "mopping_pattern": frozenset({"select"}),
    "nickname": frozenset({"sensor"}),
    "night_cycle": frozenset({"switch"}),
    "pet_avoidance": frozenset({"switch"}),
    "phase_advance": frozenset({"select"}),
    "pm25_approximate": frozenset({"sensor"}),
    "pre_wash_phase": frozenset({"switch"}),
    "program": frozenset({"select"}),
    "program_uid": frozenset({"select"}),
    "reason": frozenset({"sensor"}),
    "remote_control": frozenset({"sensor"}),
    "remote_notification_pending": frozenset({"select"}),
    "rinse": frozenset({"switch"}),
    "rinse_hold": frozenset({"switch"}),
    "running_time": frozenset({"sensor"}),
    "side_brush_runtime": frozenset({"sensor"}),
    "sleep_mode": frozenset({"select", "switch"}),
    "sound_volume": frozenset({"select", "sensor"}),
    "stain": frozenset({"switch"}),
    "start_time": frozenset({"number", "sensor"}),
    "steam_value": frozenset({"select"}),
    "stop_time": frozenset({"number", "sensor"}),
    "sw_update_state": frozenset({"sensor"}),
    "target_food_probe_temperature_c": frozenset({"number"}),
    "target_temperature": frozenset({"sensor"}),
    "target_temperature_c": frozenset({"number"}),
    "tc_sensor": frozenset({"switch"}),
    "temperature": frozenset({"sensor"}),
    "time_manager_level": frozenset({"select"}),
    "time_to_end": frozenset({"sensor"}),
    "total_cycle_counter": frozenset({"sensor"}),
    "total_runtime": frozenset({"sensor"}),
    "total_wash_cycles_count": frozenset({"sensor"}),
    "total_washing_time": frozenset({"sensor"}),
    "turbo_agitation": frozenset({"switch"}),
    "turbo_drying": frozenset({"switch"}),
    "ui_lock": frozenset({"switch"}),
    "ui_lock_mode": frozenset({"switch"}),
    "ui_locked": frozenset({"switch"}),
    "vacuum_power": frozenset({"select"}),
    "vertical_swing": frozenset({"select"}),
    "voice_language": frozenset({"sensor"}),
    "wash_level": frozenset({"select"}),
    "washing_nominal_load_weight": frozenset({"sensor"}),
    "water_hardness": frozenset({"select"}),
    "water_level": frozenset({"sensor"}),
    "water_reuse": frozenset({"switch"}),
    "water_softener_mode": frozenset({"select"}),
    "water_tank_empty": frozenset({"sensor"}),
    "water_tray_insertion_state": frozenset({"sensor"}),
    "wm_economy": frozenset({"binary_sensor"}),
    "x_fan": frozenset({"select"}),
}
