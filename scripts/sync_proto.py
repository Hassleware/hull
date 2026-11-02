"""Copy Rudder's API contract (bridge/rudder.proto) into Hull and regenerate Hull's stubs.
Run after Rudder's API changes: python scripts/sync_proto.py <path to the Rudder repo>"""
import shutil, subprocess, sys
from pathlib import Path

hull = Path(__file__).resolve().parent.parent
shutil.copy(Path(sys.argv[1]) / "bridge" / "rudder.proto", hull / "hull" / "rudder" / "rudder.proto")
subprocess.run([sys.executable, "-m", "grpc_tools.protoc", "-I", ".", "--python_out=.", "--pyi_out=.", "--grpc_python_out=.",
                "hull/rudder/rudder.proto"], cwd=hull, check=True)
print("hull/rudder/ now matches", sys.argv[1])
