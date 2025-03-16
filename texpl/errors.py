class FrameworkError(BaseException):
    def __init__(self, message: str):
        self.message = message
