#!/bin/bash
set -euo pipefail
[[ $# == 4 ]] || exit 2
template="$1"; mode="$2"; target="$3"; jobs="$4"
[[ "$template" == hl2mp || "$template" == tf ]] || exit 2
[[ "$mode" == release || "$mode" == debug ]] || exit 2
[[ "$target" == game || "$target" == plugin || "$target" == client || "$target" == server || "$target" == launcher || "$target" == shaders ]] || exit 2
[[ "$jobs" =~ ^[1-9][0-9]?$ ]] || exit 2
cd /my_mod/src
export VPC_NINJA_BUILD_MODE="$mode"
solution="_vpc_/ninja/agent_${template}_${mode}"
devtools/bin/vpc "/$template" /linux64 /ninja /define:SOURCESDK +everything /mksln "$solution"
ninja -f "$solution.ninja" -t compdb > compile_commands.json
sed -i 's/-fpredictive-commoning//g; s/-fvar-tracking-assignments//g; s|/my_mod/src|.|g' compile_commands.json
if [[ "$target" == plugin ]]; then
    ninja -f "$solution.ninja" -t targets all > "${solution}.targets"
    output=$(awk '/serverplugin_empty\.so:/ { sub(/:.*/, ""); print; exit }' "${solution}.targets")
    [[ -n "$output" ]] || { echo 'VPC did not generate the serverplugin_empty target.' >&2; exit 3; }
    ninja -f "$solution.ninja" -j"$jobs" "$output"
    mkdir -p /my_mod/game/bin/linux64
    cp "$output" /my_mod/game/bin/linux64/serverplugin_empty.so
else
    case "$target" in
        game) ninja -f "$solution.ninja" -j"$jobs" ;;
        client|server) ninja -f "$solution.ninja" -j"$jobs" "${target}_${template}" ;;
        launcher) ninja -f "$solution.ninja" -j"$jobs" "launcher_main_mod_${template}" ;;
        shaders) ninja -f "$solution.ninja" -j"$jobs" "game_shaders_${template}" ;;
    esac
fi
