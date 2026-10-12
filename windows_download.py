import sys
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
from v2t.adapter_download import main
if __name__=='__main__':raise SystemExit(main())
