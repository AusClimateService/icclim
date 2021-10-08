import datetime

import numpy as np
import pytest
from xarray import Dataset

from icclim.eca_indices import (
    Indice,
    cfd,
    csu,
    fd,
    gd4,
    hd17,
    indice_from_string,
    prcptot,
    su,
    tn10p,
    tr,
    tx90p,
)
from icclim.icclim_exceptions import InvalidIcclimArgumentError
from icclim.models.frequency import Frequency
from icclim.models.indice_config import IndiceConfig
from icclim.models.netcdf_version import NetcdfVersion
from icclim.models.quantile_interpolation import QuantileInterpolation
from icclim.tests.unit_tests.test_utils import K2C, stub_pr, stub_tas


class Test_indice_from_string:
    def test_simple(self):
        res = indice_from_string("SU")
        assert res == Indice.SU

    def test_lowercase(self):
        res = indice_from_string("tx90p")
        assert res == Indice.TX90P

    def test_error(self):
        with pytest.raises(InvalidIcclimArgumentError):
            indice_from_string("cacahuête")


@pytest.mark.parametrize("use_dask", [True, False])
def test_tn10p_interpolation_error(use_dask):
    ds = Dataset()
    ds["tas"] = stub_tas(use_dask=use_dask)
    conf = IndiceConfig(
        ds=ds,
        slice_mode=Frequency.MONTH,
        var_name=["tas"],
        netcdf_version=NetcdfVersion.NETCDF4,
        base_period_time_range=[
            ds.time.values[0].astype("M8[D]").astype("O"),
            ds.time.values[-1].astype("M8[D]").astype("O"),
        ],
        window_width=2,
        interpolation=QuantileInterpolation.LINEAR,
    )
    with pytest.raises(InvalidIcclimArgumentError):
        tn10p(conf)


@pytest.mark.parametrize("use_dask", [True, False])
def test_tn10p(use_dask):
    ds = Dataset()
    ds["tas"] = stub_tas(use_dask=use_dask)
    conf = IndiceConfig(
        ds=ds,
        slice_mode=Frequency.MONTH,
        var_name=["tas"],
        netcdf_version=NetcdfVersion.NETCDF4,
        base_period_time_range=[
            ds.time.values[0].astype("M8[D]").astype("O"),
            ds.time.values[-1].astype("M8[D]").astype("O"),
        ],
        window_width=2,
        interpolation=QuantileInterpolation.MEDIAN_UNBIASED,
        save_percentile=True,
    )
    res = tn10p(conf)
    assert res is not None


class Test_SU:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_su_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[:5] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = su(conf)
        assert res is not None
        assert res[0] == 26  # January

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_su_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(use_dask=use_dask)
        ds.tas[:5] = 50 + K2C
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=40,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = su(conf)
        assert res is not None
        assert res[0] == 5  # January


class Test_TR:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[:5] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = tr(conf)
        assert res is not None
        assert res[0] == 26  # January

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(use_dask=use_dask)
        ds.tas[:5] = 50 + K2C
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=40,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = tr(conf)
        assert res is not None
        assert res[0] == 5  # January


class Test_prcptot:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["pr"] = stub_pr(value=1, use_dask=use_dask)
        ds.pr[:10] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["pr"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = prcptot(conf)
        assert res is not None
        np.testing.assert_almost_equal(res[0], 21.0, 14)


class Test_csu:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[10:15] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = csu(conf)
        assert res is not None
        assert res[0] == 16  # January

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(use_dask=use_dask)
        ds.tas[:5] = 50 + K2C
        ds.tas[10:20] = 50 + K2C
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=40,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = csu(conf)
        assert res is not None
        assert res[0] == 10  # January


class Test_gd4:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:15] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = gd4(conf)
        assert res is not None
        expected = (26 - 4) * 21
        assert res[0] == expected  # 21 days in January above 4 degC (at 26degC)

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:15] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=5,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = gd4(conf)
        assert res is not None
        expected = (26 - 5) * 21
        assert res[0] == expected  # 21 days in January above 4 degC (at 26degC)


class Test_cfd:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:15] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = cfd(conf)
        assert res is not None
        assert res[0] == 10

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:10] = 0
        ds.tas[10:15] = 4
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=5,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = cfd(conf)
        assert res is not None
        assert res[0] == 10


class Test_fd:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:15] = 0
        ds.tas[20:25] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = fd(conf)
        assert res is not None
        assert res[0] == 15

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=26 + K2C, use_dask=use_dask)
        ds.tas[5:10] = 0
        ds.tas[10:15] = 4
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=5,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = fd(conf)
        assert res is not None
        assert res[0] == 10


class Test_hd17:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_default_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=27 + K2C, use_dask=use_dask)
        ds.tas[5:10] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = hd17(conf)
        assert res is not None
        assert res[0] == 5 * (17 + K2C)

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_custom_threshold(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=27 + K2C, use_dask=use_dask)
        ds.tas[5:10] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            threshold=5,
            netcdf_version=NetcdfVersion.NETCDF4,
        )
        res = hd17(conf)
        assert res is not None
        assert res[0] == 5 * (5 + K2C)


class TestTx90p:
    @pytest.mark.parametrize("use_dask", [True, False])
    def test_no_bootstrap_no_overlap(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=27 + K2C, use_dask=use_dask)
        ds.tas[5:10] = 0
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
            base_period_time_range=[
                datetime.datetime(2042, 1, 1),
                datetime.datetime(2042, 12, 31),
            ],
            time_range=[datetime.datetime(2043, 1, 1), datetime.datetime(2045, 12, 31)],
        )
        res = tx90p(conf)
        assert "reference_epoch" not in res.coords.keys()

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_no_bootstrap_1_year_base(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=27 + K2C, use_dask=use_dask)
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
            base_period_time_range=[
                datetime.datetime(2042, 1, 1),
                datetime.datetime(2042, 12, 31),
            ],
            time_range=[datetime.datetime(2042, 1, 1), datetime.datetime(2045, 12, 31)],
        )
        res = tx90p(conf)
        assert "reference_epoch" not in res.coords.keys()

    @pytest.mark.parametrize("use_dask", [True, False])
    def test_bootstrap_2_years(self, use_dask):
        ds = Dataset()
        ds["tas"] = stub_tas(value=27 + K2C, use_dask=use_dask)
        conf = IndiceConfig(
            ds=ds,
            slice_mode=Frequency.MONTH,
            var_name=["tas"],
            netcdf_version=NetcdfVersion.NETCDF4,
            base_period_time_range=[
                datetime.datetime(2042, 1, 1),
                datetime.datetime(2043, 12, 31),
            ],
            time_range=[datetime.datetime(2042, 1, 1), datetime.datetime(2045, 12, 31)],
        )
        res = tx90p(conf)
        assert res.attrs["reference_epoch"] == ["2042-01-01", "2043-12-31"]
