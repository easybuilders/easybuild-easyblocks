##
# Copyright 2018-2025 Ghent University
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

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.pythonpackage import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.easyblocks.generic.pythonpackage import (PythonPackage,
                                                        get_pylibdirs, find_python_cmd_from_ec, run_pip_check)
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option, PYTHONPATH, EBPYTHONPREFIXES
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
        extra_vars['default_easyblock'][0] = 'PythonPackage'
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

            self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

        self.python_cmd = None
        self.pylibdir = None
        self.all_pylibdirs = None

        # figure out whether this bundle of Python packages is being installed for multiple Python versions
        self.multi_python = 'Python' in self.cfg['multi_deps']

    def prepare_python(self):
        """Python-specific preparations."""

        if get_software_root('Python') is None:
            raise EasyBuildError("Python not included as dependency!")
        self.python_cmd = find_python_cmd_from_ec(self.log, self.cfg, required=True)

        self.all_pylibdirs = get_pylibdirs(python_cmd=self.python_cmd)
        self.pylibdir = self.all_pylibdirs[0]

        # if 'python' is not used, we need to take that into account in the extensions filter
        # (which is also used during the sanity check)
        if self.python_cmd != 'python':
            orig_exts_filter = EXTS_FILTER_PYTHON_PACKAGES
            self.cfg['exts_filter'] = (orig_exts_filter[0].replace('python', self.python_cmd), orig_exts_filter[1])

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing bundle of Python packages."""
        super(Bundle, self).prepare_step(*args, **kwargs)
        self.prepare_python()

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
        # if this Python package was installed for multiple Python versions, or if we prefer it
        use_ebpythonprefixes = False
        runtime_deps = [dep['name'] for dep in self.cfg.dependencies(runtime_only=True)]

        if 'Python' in runtime_deps:
            self.log.info("Found Python runtime dependency, so considering $EBPYTHONPREFIXES...")
            if build_option('prefer_python_search_path') == EBPYTHONPREFIXES:
                self.log.info("Preferred Python search path is $EBPYTHONPREFIXES, so using that")
                use_ebpythonprefixes = True

        if self.multi_python or use_ebpythonprefixes:
            path = ''  # EBPYTHONPREFIXES are relative to the install dir
            if path not in self.module_generator.added_paths_per_key[EBPYTHONPREFIXES]:
                txt += self.module_generator.prepend_paths(EBPYTHONPREFIXES, path)
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
                if pylibdir not in self.module_generator.added_paths_per_key[PYTHONPATH]:
                    txt += self.module_generator.prepend_paths(PYTHONPATH, pylibdir)

        return txt

    def load_module(self, *args, **kwargs):
        """
        Make sure that $PYTHONNOUSERSITE is defined after loading module file for this software."""

        super(PythonBundle, self).load_module(*args, **kwargs)

        # Don't add user site directory to sys.path (equivalent to python -s),
        # to avoid that any Python packages installed in $HOME/.local/lib affect the sanity check.
        # Required here to ensure that it is defined for sanity check commands of the bundle
        # because the environment is reset to the initial environment right before loading the module
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Python package."""

        if self.pylibdir is None:
            # Python attributes not set up yet, happens e.g. with --sanity-check-only, so do it now.
            # This also ensures the exts_filter option for extensions is set correctly.
            # Load module first to get the right python command.
            if not self.sanity_check_module_loaded:
                self.sanity_check_load_module(extension=kwargs.get('extension', False),
                                              extra_modules=kwargs.get('extra_modules', None))
            self.prepare_python()

        # inject directory path that uses %(pyshortver)s template into default value for sanity_check_paths
        # this is relevant for installations of Python bundles for multiple Python versions (via multi_deps)
        # (we can not pass this via custom_paths, since then the %(pyshortver)s template value will not be resolved)
        if not self.cfg['sanity_check_paths']:
            self.cfg['sanity_check_paths'] = {
                'files': [],
                'dirs': [os.path.join('lib', 'python%(pyshortver)s', 'site-packages')],
            }

        super(Bundle, self).sanity_check_step(*args, **kwargs)

    def _sanity_check_step_extensions(self):
        """Run the pip check for extensions if enabled"""
        super(PythonBundle, self)._sanity_check_step_extensions()

        sanity_pip_check = self.cfg['sanity_pip_check']
        unversioned_packages = set(self.cfg['unversioned_packages'])

        # The options should be set in the main EC and cannot be different between extensions.
        # For backwards compatibility and to avoid surprises enable the pip-check if it is enabled
        # in the main EC or any extension and build the union of all unversioned_packages.
        has_sanity_pip_check_mismatch = False
        all_unversioned_packages = unversioned_packages.copy()
        for ext in self.ext_instances:
            if isinstance(ext, PythonPackage):
                if ext.cfg['sanity_pip_check'] != sanity_pip_check:
                    has_sanity_pip_check_mismatch = True
                all_unversioned_packages.update(ext.cfg['unversioned_packages'])

        if has_sanity_pip_check_mismatch:
            self.log.deprecated('For bundles of PythonPackage the sanity_pip_check option '
                                'in the main EasyConfig must be used', '5.0')
            sanity_pip_check = True  # Either the main set it or any extension enabled it
        if all_unversioned_packages != unversioned_packages:
            self.log.deprecated('For bundles of PythonPackage the unversioned_packages option '
                                'in the main EasyConfig must be used', '5.0')

        if sanity_pip_check:
            run_pip_check(self.log, self.python_cmd, all_unversioned_packages)
