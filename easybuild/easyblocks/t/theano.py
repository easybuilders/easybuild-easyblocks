##
# Copyright 2018 Vrije Universiteit Brussel (VUB)
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for Theano, implemented as an easyblock

@author: Samuel Moors (Vrije Universiteit Brussel)
"""


from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.modules import get_software_root, get_software_version
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

        libblas = os.getenv('LIBBLAS')

        if libblas:
            theano_flags += ',blas.ldflags="%s"' % libblas

        txt += self.module_generator.set_environment('THEANO_FLAGS', theano_flags)

        return txt

    def sanity_check_step(self, *args, **kwargs):
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        custom_paths = {
            'files': ['bin/theano-cache', 'bin/theano-nose'],
            'dirs': ['lib/python%s/site-packages' % pyshortver],
        }
        return super(EB_Theano, self).sanity_check_step(custom_paths=custom_paths)
