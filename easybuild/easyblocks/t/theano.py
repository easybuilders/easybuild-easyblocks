from easybuild.easyblocks.generic.pythonpackage import PythonPackage
import random
import string


class EB_Theano(PythonPackage):
    """ include a random string in compiledir_format to fix problems with architecture-specific compilation
    when running the software on a heterogeneous compute cluster. """

    def make_module_extra(self):

        txt = super(EB_Theano, self).make_module_extra()

        rand_string = ''.join(random.choice(string.letters) for i in range(10))

        theano_flags = ('compiledir_format=compiledir_%s-%%(short_platform)s-%%(processor)s-'
                        '%%(python_version)s-%%(python_bitwidth)s' % rand_string)

        txt += self.module_generator.set_environment('THEANO_FLAGS', theano_flags)

        return txt
