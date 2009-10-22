import volatility.registry as registry
import volatility.conf as conf
config = conf.ConfObject()
import volatility.debug as debug

#pylint: disable-msg=C0111

def load_as(**kwargs):
    base_as = None
    error = AddrSpaceError()
    while 1:
        debug.debug("Voting round")        
        found = False
        for cls in registry.AS_CLASSES.classes:
            debug.debug("Trying {0} ".format(cls))
            try:
                base_as = cls(base_as, **kwargs)
                debug.debug("Succeeded instantiating {0}".format(base_as))
                found = True
                break
            except AssertionError, e:
                debug.debug("Failed instantiating {0}: {1}".format(cls.__name__, e), 2) 
                error.append_reason(cls.__name__, e) 
                continue

        ## A full iteration through all the classes without anyone
        ## selecting us means we are done:
        if not found:
            break

    if base_as is None:
        raise error

    return base_as

class AddrSpaceError(Exception):
    """Address Space Exception, so we can catch and deal with it in the main program"""
    def __init__(self):
        self.reasons = []
        Exception.__init__(self, "No suitable address space mapping found")
    
    def append_reason(self, driver, reason):
        self.reasons.append((driver, reason))

    def __str__(self):
        result = Exception.__str__(self) + "\nTried to open image as:\n"
        for k, v in self.reasons:
            result += " {0}: {1}\n".format(k, v)

        return result
