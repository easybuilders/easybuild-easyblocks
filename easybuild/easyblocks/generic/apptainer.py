##
# Copyright 2023 Maxime Boissonneault
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
General EasyBuild support for software, using containerized applications

@author: Maxime Boissonneault (Universite Laval, Calcul Quebec, Digital Research Alliance of Canada)
"""
import os
import re
from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError

DEFAULT_INSTALL_CMD = "/bin/sudo -iu containeruser build_container_image.sh -t sandbox "
class Apptainer(Binary):
    """
    Support for installing software via an Apptainer container
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Binary easyblock."""
        extra_vars = Binary.extra_options(extra_vars)
        extra_vars.update({
            'aliases': [[], "Commands to alias in the module.", CUSTOM],
            'apptainer_params': ["", "Default parameters for apptainer", CUSTOM],
            'container_path': ["", "Path to the container that gets created", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables."""
        super(Apptainer, self).__init__(*args, **kwargs)
        self.cfg['install_cmd'] = DEFAULT_INSTALL_CMD
        # do not prepend anything to path like binary does
        self.cfg['prepend_to_path'] = None

    def extract_step(self):
        """No extract step"""
        pass

    def make_module_req(self):
        """
        Don't extend PATH/LIBRARY_PATH/etc.
        """
        return ""

    def make_devel_module(self, create_in_builddir=False):
        """
        Make sure the easybuild directory is created in easybuild space
        NOTE TO FUTURE READER: don't ask me why this method is what defines where the easybuild directory is created
        """
        newinstalldir = self.installdir
        self.installdir = self.orig_installdir
        res = super(Apptainer, self).make_devel_module(create_in_builddir)
        self.installdir = newinstalldir
        return res

    def make_module_step(self, fake=False):
        """
        Custom module step for Apptainer: use container path directly
        """
        # For module file generation: temporarly set the container path as installdir
        self.orig_installdir = self.installdir
        if self.cfg['container_path'] is not None:
            self.installdir = self.cfg["container_path"]

        # Generate module
        res = super(Apptainer, self).make_module_step(fake=fake)

        # Reset installdir to EasyBuild values
        self.installdir = self.orig_installdir
        return res

    def make_module_extra(self, *args, **kwargs):
        """Overwritten from Application to add extra txt"""
        # make sure Apptainer is in the dependencies
        if 'Apptainer' not in [d['name'] for d in self.cfg.dependencies()]:
            raise EasyBuildError("Apptainer not included as dependency")

        txt = super(Apptainer, self).make_module_extra(*args, **kwargs)
        for alias in self.cfg["aliases"]:
            function = "apptainer exec %s %s %s" % (self.cfg["apptainer_params"], self.cfg["container_path"], alias)
            txt += self.module_generator.set_shell_function(alias, function, function)
        return txt

    def sanity_check_step(self):
        """
        Custom sanity check step for Apptainer: check that aliases run
        """

        # For module file generation: temporarly set installdir to container path
        self.orig_installdir = self.installdir
        self.installdir = self.cfg["container_path"]

        # sanity check
        res = super(Apptainer, self).sanity_check_step()

        # Reset installdir to EasyBuild values
        self.installdir = self.orig_installdir
        return res

