class JobError(Exception):
    """
    Raise this during a Job to ensure the exception's caught by
    the code that cleans up after Jobs.
    """
    pass


class UnrecognizedJobNameError(Exception):
    """
    A requested job name wasn't found in the registry
    """
    pass
