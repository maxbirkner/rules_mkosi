#!/bin/sh
set -eu

config="$TEST_SRCDIR/$TEST_WORKSPACE/$1"
section=
seed=
epoch=
while IFS= read -r line
do
    case "$line" in
        "[Output]") section=output ;;
        "[Content]") section=content ;;
        "Seed="*) [ "$section" = output ] && seed="${line#Seed=}" ;;
        "SourceDateEpoch="*) [ "$section" = content ] && epoch="${line#SourceDateEpoch=}" ;;
    esac
done < "$config"
[ "$seed" = "00000000-0000-4000-8000-000000000007" ]
[ "$epoch" = "0" ]
echo "tracer determinism settings: Seed=$seed SourceDateEpoch=$epoch"
