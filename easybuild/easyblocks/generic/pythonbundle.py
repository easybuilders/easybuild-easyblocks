##
# Copyright 2018-2018 Ghent University
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
from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class PythonBundle(Bundle):
    """
    Bundle of modules: only generate module files, nothing to build/install
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

        # need to disable templating to ensure that actual value for exts_default_options is updated...
        prev_enable_templating = self.cfg.enable_templating
        self.cfg.enable_templating = False

        # set default options for extensions according to relevant top-level easyconfig parameters
        pypkg_keys = PythonPackage.extra_options().keys()
        for key in pypkg_keys:
            if key not in self.cfg['exts_default_options']:
                self.cfg['exts_default_options'][key] = self.cfg[key]

        self.cfg['exts_default_options']['download_dep_fail'] = True
        self.log.info("Detection of downloaded extension dependencies is enabled")

        self.cfg.enable_templating = prev_enable_templating

        self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

        self.pylibdir = None

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing bundle of Python packages."""
        super(Bundle, self).prepare_step(*args, **kwargs)

        if get_software_root('Python') is None:
            raise EasyBuildError("Python not included as dependency!")

        self.pylibdir = det_pylibdir()

    def test_step(self):
        """No global test step for bundle of Python packages."""
        # required since runtest is set to True for Python packages by default
        pass

    def make_module_extra(self, *args, **kwargs):
        """Extra statements to include in module file: update $PYTHONPATH."""
        txt = super(Bundle, self).make_module_extra(*args, **kwargs)

        txt += self.module_generator.prepend_paths('PYTHONPATH', self.pylibdir)

        return txt

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Python package."""
        custom_paths = {
            'files': [],
            'dirs': [self.pylibdir],
        }
        super(Bundle, self).sanity_check_step(*args, custom_paths=custom_paths, **kwargs)
