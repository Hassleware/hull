"""Copy Rudder's API contract (bridge/rudder.proto) and its bridge (bridge/bridge.py) into Hull, and regenerate Hull's
stubs. Hull runs the bridge itself when none is running (hull/link.py). Run after Rudder's API changes:
python scripts/sync_proto.py <path to the Rudder repo>"""
import shutil, subprocess, sys
from pathlib import Path

hull = Path(__file__).resolve().parent.parent
shutil.copy(Path(sys.argv[1]) / "bridge" / "rudder.proto", hull / "hull" / "rudder" / "rudder.proto")
subprocess.run([sys.executable, "-m", "grpc_tools.protoc", "-I", ".", "--python_out=.", "--pyi_out=.", "--grpc_python_out=.",
                "hull/rudder/rudder.proto"], cwd=hull, check=True)
bridge = (Path(sys.argv[1]) / "bridge" / "bridge.py").read_text("utf-8")
bridge = bridge.replace("import rudder_pb2 as pb, rudder_pb2_grpc as rpc", "from hull.rudder import rudder_pb2 as pb, rudder_pb2_grpc as rpc")
(hull / "hull" / "rudder" / "bridge.py").write_text("# Copied from the Rudder repo by scripts/sync_proto.py: don't edit here.\n" + bridge, "utf-8")
print("hull/rudder/ now matches", sys.argv[1])
