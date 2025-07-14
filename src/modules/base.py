class PollModuleBase:
    poll_type: str
    display_name: str

    def register_handlers(self, application):
        raise NotImplementedError

    def get_poll_type(self):
        return self.poll_type

    def get_display_name(self):
        return self.display_name 