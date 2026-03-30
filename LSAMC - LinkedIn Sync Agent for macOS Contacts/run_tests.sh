#!/bin/bash
# High-Resolution Photo Extraction Test Suite

TEST_CONTACTS=(
    "Alain Amariglio"
    "Antoine Amiel"
    "Pierre-Jean Benghozi"
    "Sylvie Bernard-Curie"
    "Hugues Bazin de Jessey"
)

echo "Starting High-Res Photo Extraction Test Loop..."
echo "Mode: SIMULATION"

for name in "${TEST_CONTACTS[@]}"; do
    echo "------------------------------------------------"
    echo "TESTING: $name"
    echo "------------------------------------------------"
    python3 main.py --mode SIMULATION --name "$name"
done

echo "Test Loop Complete."
