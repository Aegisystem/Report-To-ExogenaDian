from .formato_1001 import Formato1001
from .formato_1005 import Formato1005
from .formato_1006 import Formato1006
from .formato_1007 import Formato1007
from .formato_5247 import Formato5247
from .formato_5248 import Formato5248
from .formato_5249 import Formato5249
from .formato_5250 import Formato5250

GENERADORES = {
    "1001": Formato1001,
    "1005": Formato1005,
    "1006": Formato1006,
    "1007": Formato1007,
    "5247": Formato5247,
    "5248": Formato5248,
    "5249": Formato5249,
    "5250": Formato5250,
}
