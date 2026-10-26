class ErrorAnalizador(Exception):
    pass


class DialectoNoSoportado(ErrorAnalizador):
    pass


class ErrorDeFase(ErrorAnalizador):
    def __init__(self, fase: str, indice: int, tipo: str, causa: BaseException):
        self.fase = fase
        self.indice = indice
        self.tipo = tipo
        self.causa = causa
        super().__init__(str(causa))
