from __future__ import annotations

from d365opps.sources.contracts_finder import ContractsFinderSource
from d365opps.sources.find_a_tender import FindATenderSource
from d365opps.sources.generic_web import GenericWebSource
from d365opps.sources.generic_rss import GenericRssSource
from d365opps.sources.global_sources import (
    AusTenderSource,
    AusTenderContractsSource,
    AusTenderLegacySource,
    CanadaBuysSource,
    CanadaBuysAwardsSource,
    CanadaBuysContractHistorySource,
    CanadaBuysLegacySource,
    CanadaBuysStandingOffersSource,
    CoupaPublicSourcingSource,
    EUFundingTendersSource,
    GebizSource,
    GebizIndicativeSource,
    GebizLegacySource,
    GetsAwardsSource,
    GetsLegacySource,
    IndiaCPPPSource,
    JamaicaGojepSource,
    KenyaPPIPSource,
    OcdsRegistrySource,
    OpenTenderSource,
    PhilGepsSource,
    SapBusinessNetworkDiscoverySource,
    SearchApiDiscoverySource,
    SouthAfricaETendersSource,
    SouthAfricaAwardedTendersSource,
    SouthAfricaProcurementPlansSource,
    UngmSource,
    UngmLegacySource,
    WorldBankLegacySource,
)
from d365opps.sources.public_portals import (
    GetsTenderSource,
    HilmaSource,
    IrelandETendersSource,
    TenderNedSource,
    WorldBankPotentialSource,
    WorldBankSource,
    WorldBankUpcomingSource,
)
from d365opps.sources.sam_gov import SamGovSource
from d365opps.sources.sitemap_portal import SitemapPortalSource
from d365opps.sources.ted import TedSource


class SourceAdapterFactory:
    def __init__(self) -> None:
        self._adapters = {
            ContractsFinderSource.source_name: ContractsFinderSource(),
            FindATenderSource.source_name: FindATenderSource(),
            TedSource.source_name: TedSource(),
            SamGovSource.source_name: SamGovSource(),
            GenericWebSource.source_name: GenericWebSource(),
            GenericRssSource.source_name: GenericRssSource(),
            SitemapPortalSource.source_name: SitemapPortalSource(),
            OcdsRegistrySource.source_name: OcdsRegistrySource(),
            OpenTenderSource.source_name: OpenTenderSource(),
            CanadaBuysSource.source_name: CanadaBuysSource(),
            CanadaBuysLegacySource.source_name: CanadaBuysLegacySource(),
            CanadaBuysAwardsSource.source_name: CanadaBuysAwardsSource(),
            CanadaBuysContractHistorySource.source_name: CanadaBuysContractHistorySource(),
            CanadaBuysStandingOffersSource.source_name: CanadaBuysStandingOffersSource(),
            AusTenderSource.source_name: AusTenderSource(),
            AusTenderLegacySource.source_name: AusTenderLegacySource(),
            AusTenderContractsSource.source_name: AusTenderContractsSource(),
            GetsTenderSource.source_name: GetsTenderSource(),
            GetsLegacySource.source_name: GetsLegacySource(),
            GetsAwardsSource.source_name: GetsAwardsSource(),
            UngmSource.source_name: UngmSource(),
            UngmLegacySource.source_name: UngmLegacySource(),
            WorldBankSource.source_name: WorldBankSource(),
            HilmaSource.source_name: HilmaSource(),
            WorldBankLegacySource.source_name: WorldBankLegacySource(),
            WorldBankUpcomingSource.source_name: WorldBankUpcomingSource(),
            WorldBankPotentialSource.source_name: WorldBankPotentialSource(),
            TenderNedSource.source_name: TenderNedSource(),
            GebizSource.source_name: GebizSource(),
            GebizLegacySource.source_name: GebizLegacySource(),
            GebizIndicativeSource.source_name: GebizIndicativeSource(),
            SouthAfricaETendersSource.source_name: SouthAfricaETendersSource(),
            SouthAfricaProcurementPlansSource.source_name: SouthAfricaProcurementPlansSource(),
            SouthAfricaAwardedTendersSource.source_name: SouthAfricaAwardedTendersSource(),
            EUFundingTendersSource.source_name: EUFundingTendersSource(),
            IrelandETendersSource.source_name: IrelandETendersSource(),
            PhilGepsSource.source_name: PhilGepsSource(),
            KenyaPPIPSource.source_name: KenyaPPIPSource(),
            JamaicaGojepSource.source_name: JamaicaGojepSource(),
            IndiaCPPPSource.source_name: IndiaCPPPSource(),
            CoupaPublicSourcingSource.source_name: CoupaPublicSourcingSource(),
            SapBusinessNetworkDiscoverySource.source_name: SapBusinessNetworkDiscoverySource(),
            SearchApiDiscoverySource.source_name: SearchApiDiscoverySource(),
        }

    def get(self, source_name: str):
        try:
            return self._adapters[source_name]
        except KeyError as exc:
            raise KeyError(f"No adapter registered for source '{source_name}'.") from exc
