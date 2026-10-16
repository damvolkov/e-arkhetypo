"""core.errors: typed failures of the generation engine — one root, no loose exceptions."""


##### TYPES #####
class ManagementError(Exception):
    """All e-management exceptions inherit from this root."""


class InvalidNameError(ManagementError):
    """A project name that is not a clean slug: lowercase letters, digits and underscores, starting with a letter."""


class UnknownChoiceError(ManagementError):
    """A choice switched that the template does not declare."""


class ChoiceDependencyError(ManagementError):
    """A choice kept on while something it requires was switched off."""


class MandatoryCollisionError(ManagementError):
    """A choice claims paths the template declared mandatory — those must survive every selection."""


class InfraError(ManagementError):
    """The CI library cannot serve a selection: unknown feature, unmet requires, or a token no default provides."""
