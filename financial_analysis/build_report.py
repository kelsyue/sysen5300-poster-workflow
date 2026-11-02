"""Build the report section from the R results; use the bundled document runtime."""
import csv
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent


def read(name):
    with (HERE / 'results' / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def link(paragraph, text, url):
    part = paragraph.part
    rel = part.relate_to(url, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',
                        is_external=True)
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), rel)
    run = OxmlElement('w:r')
    props = OxmlElement('w:rPr')
    color = OxmlElement('w:color')
    color.set(qn('w:val'), '24577A')
    props.append(color)
    run.append(props)
    content = OxmlElement('w:t')
    content.text = text
    run.append(content)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def main():
    row = next(r for r in read('paired_savings.csv') if r['candidate'] == 'qwen.qwen3-vl-235b-a22b')
    models = {r['model']: r for r in read('model_summary.csv')}
    before = models['claude-opus-5']
    after = models['qwen.qwen3-vl-235b-a22b']
    v = lambda key: float(row[key])
    paragraphs = [
        'The proposed change is to replace Claude Opus 5 with Qwen3 VL 235B A22B for '
        'Paper2Poster generation, conditional on meeting the existing coverage, hallucination, '
        'quality and workflow-success requirements. Cornell bills AI Platform usage by token '
        'consumption and directs users to authenticated model pricing (Cornell Information '
        'Technologies, n.d.). We therefore use the project’s dated gateway-price snapshot: '
        'Claude costs $5/$25 and Qwen $0.53/$2.66 per million input/output tokens, respectively '
        '(Project records, 2026). These are historical gross API rates, not verified batch discounts '
        'or current invoice quotations.',

        f'Our available pilot comprises {int(before["papers_requested"])} matched papers, '
        'not 30 completed papers. We reconstructed cost as (input tokens × input rate + output '
        'tokens × output rate)/1,000,000, including every recorded initial and recovery attempt. '
        f'Claude’s total was ${float(before["total_generation_cost_usd"]):.2f}, versus '
        f'${float(after["total_generation_cost_usd"]):.2f} for Qwen. Mean cost per requested paper '
        f'was ${v("before_mean_usd"):.3f} before and ${v("after_mean_usd"):.3f} after the proposed '
        f'substitution: a gross reduction of ${v("savings_per_requested_paper_usd"):.3f} '
        f'({v("relative_cost_reduction_pct"):.1f}%). Failed work remains in the denominator; '
        'copied checkpoint token totals are not counted again.',

        'To quantify paper-to-paper uncertainty, our R script resamples entire paper IDs with '
        'replacement 10,000 times, retaining all model results together, and takes the 2.5th and '
        '97.5th percentiles of mean paired savings (R boot documentation, n.d.). The approximate '
        f'95% interval is ${v("savings_ci_low"):.3f}–${v("savings_ci_high"):.3f} per requested paper. '
        f'For 30 similar papers, projected expected spend is ${v("projected_before_usd"):.2f} '
        f'versus ${v("projected_after_usd"):.2f}, saving ${v("projected_savings_usd"):.2f} '
        f'(95% interval ${v("expected_savings_ci_low"):.2f}–${v("expected_savings_ci_high"):.2f}). '
        'This interval is conditional on fixed prices, representative pilot papers and the '
        'recorded retry policy; it is not a prediction interval for a future invoice.',

        f'Financial adoption is not yet justified: Qwen passed automatic workflow checks on '
        f'{int(after["eventual_workflow_successes"])}/15 papers, versus '
        f'{int(before["eventual_workflow_successes"])}/15 for Claude, and full quality qualification '
        'remains unresolved. Judging, reference-sheet creation, local compute and staff time are '
        'excluded from these generation costs. Using the $43.46/hour technical-writer median wage '
        'only as a sensitivity proxy (U.S. Bureau of Labor Statistics, n.d.), approximately '
        f'{v("extra_review_break_even_seconds"):.0f} additional review seconds per paper would '
        'consume the estimated API saving. No labor saving is claimed. Measure review and '
        'correction time, include recurring evaluation and implementation expenses, and verify '
        'all acceptance gates before deployment. Cornell’s team-level monthly allowance may '
        'also reduce realized cash savings relative to gross token-cost savings.'
    ]
    count = len(re.findall(r"\S+", ' '.join(paragraphs)))
    assert 300 <= count <= 500, count
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(.78)
    section.left_margin = section.right_margin = Inches(.85)
    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.08
    normal.paragraph_format.space_after = Pt(9)
    for name in ('Title', 'Heading 1'):
        doc.styles[name].font.name = 'Calibri'
        doc.styles[name].font.color.rgb = RGBColor.from_string('20384A')
    title = doc.add_heading('Financial Impacts', level=0)
    title.paragraph_format.space_after = Pt(12)
    for text in paragraphs:
        p = doc.add_paragraph(text)
        p.paragraph_format.widow_control = True
    doc.add_page_break()
    doc.add_heading('References', level=1)
    p = doc.add_paragraph('Cornell Information Technologies. (n.d.). ')
    link(p, 'AI Platform: Cost.', 'https://it.cornell.edu/aiplatform')
    p.add_run(' Retrieved November 1, 2026. Exact model prices require authenticated access; '
              'the financial calculations use the project’s historical snapshot.')
    doc.add_paragraph('Project records. (2026, October 31). Cornell AI Gateway price snapshot '
                     'and poster-generation attempt logs. Repository files: '
                     'harness/config/prices.yaml; harness/data/latex/runs.csv; '
                     'harness/data/latex/recovery_attempts.csv. Source identified in the snapshot: '
                     'https://api.ai.it.cornell.edu/model/info (authenticated). '
                     'Reproducible analysis: financial_analysis/financial_impacts.R.')
    p = doc.add_paragraph('R boot documentation. (n.d.). ')
    link(p, 'Bootstrap resampling', 'https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.html')
    p.add_run(' and ')
    link(p, 'Nonparametric bootstrap confidence intervals.',
         'https://stat.ethz.ch/R-manual/R-devel/library/boot/html/boot.ci.html')
    p.add_run(' Retrieved November 1, 2026.')
    p = doc.add_paragraph('U.S. Bureau of Labor Statistics. (n.d.). ')
    link(p, 'Technical writers. Occupational Outlook Handbook.',
         'https://www.bls.gov/ooh/media-and-communication/technical-writers.htm')
    p.add_run(' Retrieved November 1, 2026. May 2025 median wage: $43.46/hour; '
              'used as a sensitivity proxy, excluding benefits and overhead.')
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run('Financial impact analysis | ')
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    doc.core_properties.title = 'Financial Impacts — Paper2Poster Model Selection'
    doc.core_properties.subject = 'Observed pilot API costs and paired bootstrap confidence intervals'
    doc.core_properties.author = 'Project team'
    output = HERE / 'Financial_Impacts.docx'
    doc.save(output)
    (HERE / 'results/report_word_count.txt').write_text(f'{count} words in the Discussion section; references excluded.\n')
    print(f'Created {output}; body word count: {count}')


if __name__ == '__main__':
    main()
