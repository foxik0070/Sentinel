class BaseDetector:
    """
    Abstraktni zakladni trida pro vsechny pluginy.
    Definuje standardni rozhrani ocekavane plugin managerem.
    """
    def __init__(self, name: str, config_params: dict = None):
        """
        Inicializace detektoru.
        
        Args:
            name (str): Jmeno pluginu (např. 'detector_icinga').
            config_params (dict): Parametry nactene z config.yaml.
        """
        self.name = name
        self.config_params = config_params or {}

    def process(self, lines: list, file_path: str):
        """
        Hlavni zpracovavaci metoda volana Watcherem/PluginManagerem.
        Musi byt implementovana potomkem.
        
        Args:
            lines (list): List novych radku prectenych ze souboru.
            file_path (str): Absolutni cesta ke sledovanemu souboru.
        """
        raise NotImplementedError(f"Plugin '{self.name}' neimplementuje metodu process().")
