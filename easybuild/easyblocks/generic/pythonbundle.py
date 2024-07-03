##
# Copyright 2018-2024 Ghent University
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
EasyBuild support for installing a bundle of Python packages, implemented as a generic easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
import sys

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.pythonpackage import EBPYTHONPREFIXES, EXTS_FILTER_PYTHON_PACKAGES
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, get_pylibdirs, pick_python_cmd
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import which
from easybuild.tools.modules import get_software_root
import easybuild.tools.environment as env


class PythonBundle(Bundle):
    """
    Bundle of PythonPackages: install Python packages as extensions in a bundle
    Defines custom sanity checks and module environment
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to bundles of Python packages."""
        if extra_vars is None:
            extra_vars = {}
        # combine custom easyconfig parameters of Bundle & PythonPackage
        extra_vars = Bundle.extra_options(extra_vars)
        return PythonPackage.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize PythonBundle easyblock."""
        super(PythonBundle, self).__init__(*args, **kwargs)

        self.cfg['exts_defaultclass'] = 'PythonPackage'
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES

        # need to disable templating to ensure that actual value for exts_default_options is updated...
        with self.cfg.disable_templating():
            # set default options for extensions according to relevant top-level easyconfig parameters
            pypkg_keys = PythonPackage.extra_options().keys()
            for key in pypkg_keys:
                if key not in self.cfg['exts_default_options']:
                    self.cfg['exts_default_options'][key] = self.cfg[key]

            self.cfg['exts_default_options']['download_dep_fail'] = True
            self.log.info("Detection of downloaded extension dependencies is enabled")

            self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

        self.pylibdir = None
        self.all_pylibdirs = []

        # figure out whether this bundle of Python packages is being installed for multiple Python versions
        self.multi_python = 'Python' in self.cfg['multi_deps']

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing bundle of Python packages."""
        super(Bundle, self).prepare_step(*args, **kwargs)

        python_root = get_software_root('Python')
        if python_root is None:
            raise EasyBuildError("Python not included as dependency!")

        # when system Python is used, the first 'python' command in $PATH will not be $EBROOTPYTHON/bin/python,
        # since $EBROOTPYTHON is set to just 'Python' in that case
        # (see handling of allow_system_deps in EasyBlock.prepare_step)
        if which('python') == os.path.join(python_root, 'bin', 'python'):
            # if we're using a proper Python dependency, let det_pylibdir use 'python' like it does by default
            python_cmd = None
        else:
            # since det_pylibdir will use 'python' by default as command to determine Python lib directory,
            # we need to intervene when the system Python is used, by specifying version requirements
            # to pick_python_cmd so the right 'python' command is used;
            # if we're using the system Python and no Python version requirements are specified,
            # use major/minor version of Python being used in this EasyBuild session (as we also do in PythonPackage)
            req_py_majver = self.cfg['req_py_majver']
            if req_py_majver is None:
                req_py_majver = sys.version_info[0]
            req_py_minver = self.cfg['req_py_minver']
            if req_py_minver is None:
                req_py_minver = sys.version_info[1]

            python_cmd = pick_python_cmd(req_maj_ver=req_py_majver, req_min_ver=req_py_minver)

        self.all_pylibdirs = get_pylibdirs(python_cmd=python_cmd)
        self.pylibdir = self.all_pylibdirs[0]

        # if 'python' is not used, we need to take that into account in the extensions filter
        # (which is also used during the sanity check)
        if python_cmd:
            orig_exts_filter = EXTS_FILTER_PYTHON_PACKAGES
            self.cfg['exts_filter'] = (orig_exts_filter[0].replace('python', python_cmd), orig_exts_filter[1])

    def extensions_step(self, *args, **kwargs):
        """Install extensions (usually PythonPackages)"""
        # don't add user site directory to sys.path (equivalent to python -s)
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)
        super(PythonBundle, self).extensions_step(*args, **kwargs)

    def test_step(self):
        """No global test step for bundle of Python packages."""
        # required since runtest is set to True for Python packages by default
        pass

    def make_module_extra(self, *args, **kwargs):
        """Extra statements to include in module file: update $PYTHONPATH."""
        txt = super(Bundle, self).make_module_extra(*args, **kwargs)

        # update $EBPYTHONPREFIXES rather than $PYTHONPATH
        # if this Python package was installed for multiple Python versions
        if self.multi_python:
            txt += self.module_generator.prepend_paths(EBPYTHONPREFIXES, '')
        else:

            # the temporary module file that is generated before installing extensions
            # must add all subdirectories to $PYTHONPATH without checking existence,
            # otherwise paths will be missing since nothing is there initially
            if self.current_step == 'extensions':
                new_pylibdirs = self.all_pylibdirs
            else:
                new_pylibdirs = [
                    lib_dir for lib_dir in self.all_pylibdirs
                    if os.path.exists(os.path.join(self.installdir, lib_dir))
                ]

            for pylibdir in new_pylibdirs:
                txt += self.module_generator.prepend_paths('PYTHONPATH', pylibdir)

        return txt

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Python package."""

        # inject directory path that uses %(pyshortver)s template into default value for sanity_check_paths
        # this is relevant for installations of Python bundles for multiple Python versions (via multi_deps)
        # (we can not pass this via custom_paths, since then the %(pyshortver)s template value will not be resolved)
        if not self.cfg['sanity_check_paths']:
            self.cfg['sanity_check_paths'] = {
                'files': [],
                'dirs': [os.path.join('lib', 'python%(pyshortver)s', 'site-packages')],
            }

        super(Bundle, self).sanity_check_step(*args, **kwargs)
