from easybuild.easyblocks.generic.pythonpackage import PythonPackage
import os
import random
import string


class EB_Theano(PythonPackage):
    """
    1) Include a random string in compiledir_format to fix problems with architecture-specific compilation
       when running the software on a heterogeneous compute cluster.
    2) Make sure Theano uses the BLAS libraries.
    """
    def make_module_extra(self):

        txt = super(EB_Theano, self).make_module_extra()

        rand_string = ''.join(random.choice(string.letters) for i in range(10))

        theano_flags = ('compiledir_format=compiledir_%%(short_platform)s-%%(processor)s-'
                        '%%(python_version)s-%%(python_bitwidth)s-%s' % rand_string)

        theano_flags += ',blas.ldflags="%s"' % os.getenv('LIBBLAS')

        txt += self.module_generator.set_environment('THEANO_FLAGS', theano_flags)

        return txt
