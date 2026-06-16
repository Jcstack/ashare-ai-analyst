import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"

interface ReasoningPanelProps {
  reasoning: string
}

export function ReasoningPanel({ reasoning }: ReasoningPanelProps) {
  const steps = reasoning.split("\n").filter((line) => line.trim())

  return (
    <Accordion type="single" collapsible defaultValue="reasoning">
      <AccordionItem value="reasoning" className="border-none">
        <AccordionTrigger className="text-sm font-semibold py-0 hover:no-underline">
          分析推理过程
        </AccordionTrigger>
        <AccordionContent className="pt-3">
          {steps.length > 1 ? (
            <div className="space-y-2">
              {steps.map((step, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-accent-primary/20 text-accent-primary text-xs flex items-center justify-center font-medium mt-0.5">
                    {i + 1}
                  </span>
                  <span className="text-sm text-muted-foreground leading-relaxed">{step}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="whitespace-pre-wrap text-sm text-muted-foreground leading-relaxed">
              {reasoning}
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
