# Author: Pavel Grochal (INUITS)
# License: GPLv2

"""
EasyBuild mix of CMake configure step and Ninja build install.
@author: Pavel Grochal (INUITS)
"""
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.mesonninja import MesonNinja


class CMakeNinja(CMakeMake, MesonNinja):

    def configure_step(self, *args, **kwargs):
        CMakeMake.configure_step(self, *args, **kwargs)

    def build_step(self, *args, **kwargs):
        MesonNinja.build_step(self, *args, **kwargs)

    def install_step(self, *args, **kwargs):
        MesonNinja.install_step(self, *args, **kwargs)
