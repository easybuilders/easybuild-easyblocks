"""
EasyBuild support for ICON, implemented as an easyblock

@author: Jarne Renders (Vrije Universiteit Brussel)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools import toolchain
from easybuild.tools.build_log import EasyBuildError


class EB_ICON(ConfigureMake):
    """Support for building/installing ICON."""

    def configure_step(self):
        """Configure ICON build, setting toolchain-specific compiler flags."""
        comp_fam = self.toolchain.comp_family()

        self.cfg.update('configopts', 'MPI_LAUNCH=mpirun')

        if comp_fam in (toolchain.GCC, toolchain.INTELCOMP):
            # LIBS is identical for foss and intel (no CUDA libraries, both need
            # -Wl,--disable-new-dtags); NVHPC sets its own LIBS below.
            self.cfg.update('configopts', (
                'LIBS="'
                '    -Wl,--disable-new-dtags -Wl,--as-needed'
                '    -lxml2'
                '    -lfyaml'
                '    -leccodes_f90 -leccodes'
                '    $LIBLAPACK'
                '    -lnetcdff -lnetcdf'
                '    -lstdc++'
                '"'
            ))

        if comp_fam == toolchain.NVHPC:
            # Following config/mpim/bullseye.gpu.nvhpc and config/dkrz/levante.gpu.nvhpc-24.7
            cuda_sm = self.cfg.get_cuda_cc_template_value('cuda_sm_comma_sep')
            self.cfg.update('configopts', (
                'FCFLAGS="$FCFLAGS $CPPFLAGS'
                '    -Mrecursive -Mallocatable=03 -Mstack_arrays -Minfo=accel,inline'
                f'    -acc=gpu,verystrict -gpu={cuda_sm}"'
            ))

            # nvcc's plain -arch= flag only accepts a single target (unlike NVHPC's -gpu=
            # flag above), so build a real multi-arch fat binary via -gencode instead.
            cuda_ccs = self.cfg.get_cuda_cc_template_value('cuda_int_comma_sep')
            nvcc_gencode = ' '.join(
                f'-gencode arch=compute_{cc},code=sm_{cc}' for cc in cuda_ccs.split(',')
            )
            self.cfg.update('configopts', f'CUDAFLAGS="-ccbin=$CXX -O3 {nvcc_gencode}"')

            self.cfg.update('configopts', 'ICON_CFLAGS="-O3"')
            self.cfg.update('configopts', 'ICON_LDFLAGS="-Wl,--disable-new-dtags"')
            self.cfg.update('configopts', (
                'LIBS="'
                '    -Wl,--as-needed'
                '    -lxml2'
                '    -lfyaml'
                '    -leccodes_f90 -leccodes'
                '    $LIBLAPACK'
                '    -lnetcdff -lnetcdf'
                '    -lcudart -lcuda'
                '    -lstdc++'
                '"'
            ))
        elif comp_fam == toolchain.GCC:
            # Following config/mpim/bullseye.openmpi.gcc-14.2.0
            self.cfg.update('configopts', 'FCFLAGS="$FCFLAGS $CPPFLAGS"')
            self.cfg.update('configopts', 'ICON_CFLAGS="-O3"')
            # Set lock_assert=0 instead of MPI_MODE_NOCHECK for a MPI_Win_lock()
            self.cfg.update('configopts', 'ICON_FCFLAGS="-O3 -DDO_NOT_COMBINE_PUT_AND_NOCHECK"')
            self.cfg.update('configopts', 'ICON_OCEAN_FCFLAGS="-O3 -fno-tree-loop-vectorize"')
        elif comp_fam == toolchain.INTELCOMP:
            # Following config/ecmwf/atos2020.intel-2025.0
            self.cfg.update('configopts', 'CFLAGS="$CFLAGS -qno-opt-dynamic-align"')
            self.cfg.update('configopts', 'ICON_CFLAGS="-O3 -ftz"')
            self.cfg.update('configopts', 'ICON_BUNDLED_CFLAGS="-ftz"')
            # Set lock_assert=0 instead of MPI_MODE_NOCHECK for a MPI_Win_lock()
            self.cfg.update('configopts', (
                'ICON_FCFLAGS="'
                '    -O3 -ftz -fp-model=precise'
                '    -assume realloc_lhs'
                '    -DDO_NOT_COMBINE_PUT_AND_NOCHECK'
                '"'
            ))
            self.cfg.update('configopts', 'ICON_BUNDLED_FCFLAGS="-ftz"')
            self.cfg.update('configopts', (
                'ICON_OCEAN_FCFLAGS="'
                '    -O3 -ftz -fp-model=precise'
                '    -assume norealloc_lhs'
                '"'
            ))
            self.cfg.update('configopts', 'ICON_ECRAD_FCFLAGS="-qno-opt-dynamic-align -no-fma"')
        else:
            raise EasyBuildError("EB_ICON does not support toolchain compiler family '%s'", comp_fam)

        super().configure_step()
