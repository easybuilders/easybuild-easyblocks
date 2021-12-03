##
# Copyright 2014-2021 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of the University of Ghent (http://ugent.be/hpc).
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
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-94.html
##
#
# Modifications by Thomas Hoffmann, EMBL Heidelberg, structures-it@embl.de, 2021/05:
#  - allow for adding additionals QAs -> other archs than x86_64-intel8
#  - support Python3
#  - allow python multi_deps; link into lib/python%(pyshortver)s/site-packages, but take care
#    that mod%(version) is still working
#  - derive from PythonPackage
#  - provide bin/mod -> bin/mod%(version)s
"""
EasyBuild support for installing Modeller, implemented as an easyblock

@author: Pablo Escobar Lopez (SIB - University of Basel)
@author: Thomas Hoffmann (EMBL Heidelberg)
"""

import os

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd_qa
from distutils.version import LooseVersion
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.modules import get_software_version
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.filetools import mkdir
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.easyblocks.python import EBPYTHONPREFIXES
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir


class EB_Modeller(PythonPackage):
    """Support for installing Modeller."""

    @staticmethod
    def extra_options(extra_vars=None):
        extra_vars = PythonPackage.extra_options()
        extra_vars.update({
            'qa': [
                {'dummyquestion': 'dummyanswer'},
                'Additional questions and answers not covered by the current EasyBlock',
                CUSTOM]})
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Easyblock constructor; define class variables."""
        super(EB_Modeller, self).__init__(*args, **kwargs)
        self.loosever = LooseVersion(self.version)
        self.multi_python = 'Python' in self.cfg['multi_deps']
        # by default modeller tries to install to $HOME/bin/modeller{version}
        # get this path to use it in the question/answer
        default_install_path = os.path.join(os.path.expanduser('~'), 'bin', 'modeller%s' % self.cfg['version'])
        self.qa = {
             'Select the type of your computer from the list above [1]:': '',
             'Select the type of your computer from the list above [2]:': '',
             'Select the type of your computer from the list above [3]:': '',
             'Select the type of your computer from the list above [4]:': '',
             'Select the type of your computer from the list above [5]:': '',
             'Select the type of your computer from the list above [6]:': '',
             "[%s]:" % default_install_path: self.installdir,
             'http://salilab.org/modeller/registration.html:': self.cfg["key"],
             'https://salilab.org/modeller/registration.html:': self.cfg["key"],
             'Press <Enter> to begin the installation:': '',
             'Press <Enter> to continue:': ''
        }
        self.qa.update(self.cfg['qa'])
        self.arch_ = None
    def configure_step(self):
        """ Skip configuration step """
        pass

    def build_step(self):
        """ Skip build step """
        pass

    def install_step(self):
        """Interactive install of Modeller."""
        python_looseversion = LooseVersion(get_software_version('Python'))
        if self.loosever < LooseVersion('9.10') and python_looseversion >= LooseVersion('3'):
            raise EasyBuildError("Modeller version < 9.10 does not support Python3")
        if self.cfg['key'] is None:
            raise EasyBuildError("No license key specified (easyconfig parameter 'key')")
        cmd = "%s/Install" % self.cfg['start_dir']
        run_cmd_qa(cmd, self.qa, log_all=True, simple=True)
        # Determine lib/arch_ according to modeller's architecure naming scheme. After running the installer for the
        # first time, there should only be one subdirectory in lib, e.g. x86_64-intel8. Save this value for later multi_dep
        # interations, as lib will already be populated.
        if not self.arch_:
            self.arch_ = os.listdir(os.path.join(self.installdir, 'lib'))[0]
        # _modeller.so is provided for different Python versions, namely 2.5, 3.0, 3.2, and >=3.3 (still the case for Mod. 10.2)
        # We link the _modeller.so and %(installdir)s/modlib into %(installdir)s/lib/python%(pyshortver)s/site-packages
        # in order to allow multi_deps python
        py_api_dirname = 'python2.5'
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        python_path = os.path.join(self.installdir, 'lib', 'python%s', 'site-packages') % pyshortver
        if python_looseversion >= LooseVersion('3.0'):
            py_api_dirname = 'python3.0'
        if python_looseversion >= LooseVersion('3.2'):
            py_api_dirname = 'python3.2'
        if python_looseversion >= LooseVersion('3.3'):
            py_api_dirname = 'python3.3' 
        mkdir(python_path, True)
        os.listdir(python_path)
        for src in os.listdir(os.path.join(self.installdir, 'modlib')):
            os.symlink(os.path.join('..', '..', '..', 'modlib', src), os.path.join(python_path, src))
        for src in os.listdir(os.path.join(self.installdir, 'lib', self.arch_, py_api_dirname)):
            os.symlink(os.path.join('..', '..', self.arch_, py_api_dirname, src), os.path.join(python_path, src))
        # link all shared libraries from the architecture specific directory (e.g. x86_64-intel8) into lib. Exclude
        # _modeller.so, as this library is for Python <2.5.
        for src in [
            f for f in os.listdir(os.path.join(self.installdir, 'lib', self.arch_))
            if os.path.isfile(os.path.join(self.installdir, 'lib', self.arch_, f))
            and f != '_modeller.'+get_shared_lib_ext()]:
                dst = os.path.join(self.installdir, 'lib', src)
                if not os.path.exists(dst):
                    os.symlink(os.path.join(self.arch_, src), dst)
        # provide bin/mod -> bin/mod%(version)s
        if not os.path.exists(os.path.join(self.installdir, 'bin', 'mod')):
            os.symlink(os.path.join('mod' + self.version), os.path.join(self.installdir, 'bin', 'mod')),

    def make_module_extra(self):
        """Set EBPYTHONPREFIXES or PYTHONPATH"""
        txt = super(EB_Modeller, self).make_module_extra()
        if self.multi_python:
            txt += self.module_generator.prepend_paths(EBPYTHONPREFIXES, '')
        else:
            txt += self.module_generator.prepend_paths('PYTHONPATH', [det_pylibdir()])
        self.log.debug("make_module_extra added %s" % txt)
        return txt

    def sanity_check_step(self):
        """Custom sanity check for Modeller."""
        custom_paths = {
            'files': ["bin/mod%s" % self.version, "bin/modpy.sh", 'bin/mod'],
            'dirs': ["doc", "lib", "examples"],
        }
        if self.loosever < LooseVersion('10.0'):
            custom_paths['files'].append('bin/modslave.py')
        super(EB_Modeller, self).sanity_check_step(custom_paths=custom_paths)
