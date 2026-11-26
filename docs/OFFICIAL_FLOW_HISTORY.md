# Official issuer history recovery

BlackRock's official fund-download endpoint supplies XML Spreadsheet workbooks. The SLV workbook includes literal ampersands in disclaimer hyperlink attributes. The parser repairs only bare XML ampersands, verifies the fund name in the Performance sheet, reads the named Historical columns, and supports both published date formats. It rejects duplicate/future dates, invalid numeric fields and entity declarations.

SLV, IWM, SHY, SGOV, IBIT and ETHA are read from their own official portfolio IDs. Daily creation/redemption estimates are change in published shares outstanding multiplied by same-day NAV. Beginning assets are estimated from same-source NAV times shares. These are estimates of primary-market activity, not observed investor cash transfers.

GLD is read from the issuer's official US historical archive. Its estimate is current total net assets minus prior net assets adjusted by the issuer NAV ratio. Market prices and secondary-market trading volume are not used. Its beginning assets are the issuer's published total net assets.

The session calendar covers up to 25 years so the collector no longer truncates long source histories to 850 calendar days. Only closed XNYS sessions are used. Missing adjacent observations and NAV discontinuities larger than the stated 2/3–1.5 ratio bounds interrupt flow history; neither gaps nor suspected splits create synthetic flows. The continuous suffix alone feeds horizon calculations. An issuer's earlier raw history start is distinct from the usable continuous period.

All outputs retain source URL/hash, source date, observed history coverage and ISSUER_DERIVED_ESTIMATE precision. Historical vintages/publication times are not retroactively verified. Sources are not spliced and these observations do not promote a strategy to production. Young funds cannot have histories predating inception; annual strength needs sufficient independent annual references.

Remaining limitations: ETFdb access denial is not repaired; official and separate observational alternatives provide continuity. SPY/DIA/QQQ and USCF do not acquire long daily histories from this change. TBF3 positioning and validated forward-performance evidence cannot be manufactured from NAV/share data.
