import pytest
import os
import subprocess
from unittest.mock import patch, MagicMock
from src.bridge.image_optim import optimize_image
from src.bridge.contact_macos import ContactMacOSBridge

# --- Image Optim Tests ---

def test_optimize_image_file_not_found(tmp_path):
    assert optimize_image("non_existent.png", str(tmp_path / "out.jpg")) is False

@patch("subprocess.run")
def test_optimize_image_success(mock_run, tmp_path):
    # Mock first call for dimensions, second for sips
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="pixelWidth: 2000\npixelHeight: 2000"),
        MagicMock(returncode=0)
    ]
    
    input_file = tmp_path / "in.png"
    input_file.write_text("dummy content")
    output_file = tmp_path / "out.heic"
    
    result = optimize_image(str(input_file), str(output_file))
    
    assert result is True
    assert mock_run.call_count == 2

# --- Contact MacOS Bridge Tests ---

@patch("subprocess.run")
def test_bridge_find_contact_success(mock_run):
    # Mock successful osascript execution returning a single match
    mock_run.return_value = MagicMock(returncode=0, stdout="ID:1234AD|NAME:Test Name|COMP:Apple|NOTE:Hello World")
    
    bridge = ContactMacOSBridge(mode="SIMULATION")
    res = bridge.find_contact("Test Name")
    
    assert res["success"] is True
    assert res["ambiguous"] is False
    assert res["id"] == "1234AD"
    assert res["name"] == "Test Name"

@patch("subprocess.run")
def test_bridge_find_contact_multiple(mock_run):
    # Mock multiple results
    mock_run.return_value = MagicMock(returncode=0, stdout="ID:1|NAME:R1|COMP:C1|NOTE:N1, ID:2|NAME:R2|COMP:C2|NOTE:N2")
    
    bridge = ContactMacOSBridge(mode="SIMULATION")
    res = bridge.find_contact("Richard")
    
    assert res["success"] is True
    assert res["ambiguous"] is True
    assert len(res["matches"]) == 2

def test_bridge_simulation_mode_update():
    bridge = ContactMacOSBridge(mode="SIMULATION")
    res = bridge.update_contact("1234", {"role": "CEO"})
    
    assert res["success"] is True
    assert res["simulated"] is True
