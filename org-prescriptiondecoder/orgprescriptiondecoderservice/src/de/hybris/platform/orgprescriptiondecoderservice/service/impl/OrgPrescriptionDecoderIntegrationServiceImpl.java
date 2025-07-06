/*
 * Copyright (c) 2025 SAP SE or an SAP affiliate company. All rights reserved. JnJGlobalExtendedOrderDataIntegrationServiceImpl
 */
package de.hybris.platform.orgprescriptiondecoderservice.service.impl;

import de.hybris.platform.orgprescriptiondecoderservice.client.OrgLifecareRestTemplateFactory;
import de.hybris.platform.orgprescriptiondecoderservice.data.ContentsData;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgLLMRequestData;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgLLMResponseData;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgPrescriptionDecoderRequestData;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgPrescriptionDecoderResponseData;
import de.hybris.platform.orgprescriptiondecoderservice.data.PartsData;
import de.hybris.platform.orgprescriptiondecoderservice.service.OrgPrescriptionDecoderIntegrationService;
import de.hybris.platform.servicelayer.config.ConfigurationService;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

import org.apache.commons.lang3.ObjectUtils;
import org.apache.commons.lang3.StringUtils;
//Added for logging
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestOperations;
import org.springframework.web.util.UriComponentsBuilder;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.gson.Gson;


/**
 *
 */
public class OrgPrescriptionDecoderIntegrationServiceImpl implements OrgPrescriptionDecoderIntegrationService
{
	/**
	 *
	 */
	private static final String MISTRAL_AUTH_KEY = "mistral.medicines.extract.auth.key";

	private OrgLifecareRestTemplateFactory orgLifecareRestTemplateFactory;

	private static final Logger LOG = LoggerFactory.getLogger(OrgPrescriptionDecoderIntegrationServiceImpl.class);
	private static final String URL_CONFIG = "gemini.medicines.extract.api.url";
	private static final String KEY_CONFIG = "gemini.medicines.extract.key";
	private static final String BEARER_AUTH_TOKEN = MISTRAL_AUTH_KEY;
	private ConfigurationService configurationService;

	@Override
	public List<String> getDecodedMedicineList(final OrgPrescriptionDecoderRequestData orgPrescriptionDecoderRequestData)
	{
		final String markDownString = getDecodedMarkDownData(orgPrescriptionDecoderRequestData);
		return getMedicinesList(markDownString);
	}

	@Override
	public String getDecodedMarkDownData(final OrgPrescriptionDecoderRequestData orgPrescriptionDecoderRequestData)
	{
		String markDownString = StringUtils.EMPTY;
		final HttpHeaders headers = new HttpHeaders();
		headers.setBearerAuth(configurationService.getConfiguration().getString(MISTRAL_AUTH_KEY));
		final RestOperations restOperations = orgLifecareRestTemplateFactory.createTemplate();
		final HttpEntity<OrgPrescriptionDecoderRequestData> httpEntity = new HttpEntity<>(orgPrescriptionDecoderRequestData,
				headers);
		LOG.info("############request from decoding prescription using OCR #####");
		final String requestJson = new Gson().toJson(httpEntity.getBody());
		LOG.info("order create request body: {}", requestJson);
		try
		{
			final ResponseEntity<OrgPrescriptionDecoderResponseData> response = restOperations.postForEntity(configurationService
					.getConfiguration().getString("mistral.medicines.extract.url", "https://api.mistral.ai/v1/ocr"), httpEntity,
					OrgPrescriptionDecoderResponseData.class);

			final OrgPrescriptionDecoderResponseData prescriptionDecodedResponseData = response.getBody();

			if (ObjectUtils.isNotEmpty(prescriptionDecodedResponseData)
					&& ObjectUtils.isNotEmpty(prescriptionDecodedResponseData.getPages().get(0).getMarkdown()))
			{
				markDownString = prescriptionDecodedResponseData.getPages().get(0).getMarkdown();
				markDownString = markDownString.replaceAll("\\r?\\n", " ").replaceAll("\\s+", " ").trim();
			}
		}
		catch (final Exception ex)
		{
			final String message = "Exception happened during call to " + ex;
			ex.printStackTrace();
		}
		return markDownString;
	}

	/**
	 *
	 * Extracts medicine names from OCR text using an LLM.
	 *
	 * @param ocrText
	 *           The OCR (Optical Character Recognition) text containing medicine names.
	 * @return A list of extracted medicine names.
	 */
	@Override
	public List<String> getMedicinesList(final String ocrText)
	{
		List<String> responseList = new ArrayList<>();
		if (ObjectUtils.isNotEmpty(ocrText))
		{
			final String prompt = "Extract only the medicine names from the following OCR text and return them in a JSON array format, like [\"MedicineA\", \"MedicineB\"]. Ignore dosages, frequencies, or other text.\n\nOCR Text:\n"
					+ ocrText;
			final OrgLLMRequestData requestData = new OrgLLMRequestData();
			final ContentsData contents = new ContentsData();
			final PartsData parts = new PartsData();
			parts.setText(prompt);
			contents.setParts(parts);
			requestData.setContents(contents);
			final HttpHeaders headers = new HttpHeaders();
			headers.setContentType(MediaType.APPLICATION_JSON);
			final RestOperations restOperations = orgLifecareRestTemplateFactory.createTemplate();
			final HttpEntity<OrgLLMRequestData> entity = new HttpEntity<>(requestData, headers);
			final String url = configurationService.getConfiguration().getString(URL_CONFIG);
			final String key = configurationService.getConfiguration().getString(KEY_CONFIG);
			if (Objects.isNull(url) || url.trim().isEmpty() || Objects.isNull(key) || key.trim().isEmpty())
			{
				LOG.error("LLM API URL or Key not configured. URL: {}, Key: {}", url, key);
				return responseList;
			}
			final String urlTemplate = UriComponentsBuilder.fromHttpUrl(url).queryParam("key", key).build().toUriString();
			final String requestJson = new Gson().toJson(requestData); // Correctly serialize requestData, not httpEntity.getBody() directly
			LOG.info("LLM request body: {}", requestJson);
			try
			{
				final ResponseEntity<OrgLLMResponseData> response = restOperations.postForEntity(urlTemplate, entity,
						OrgLLMResponseData.class);


				final OrgLLMResponseData responseBody = response.getBody();

				if (ObjectUtils.isNotEmpty(responseBody) && responseBody.getCandidates() != null
						&& !responseBody.getCandidates().isEmpty() && responseBody.getCandidates().get(0).getContent() != null
						&& responseBody.getCandidates().get(0).getContent().getParts() != null
						&& !responseBody.getCandidates().get(0).getContent().getParts().isEmpty()
						&& responseBody.getCandidates().get(0).getContent().getParts().get(0).getText() != null)
				{
					final String responseString = responseBody.getCandidates().get(0).getContent().getParts().get(0).getText();
					LOG.debug("Raw LLM response string: {}", responseString);
					String jsonText = responseString;
					if (jsonText.startsWith("```json") && jsonText.endsWith("```"))
					{
						jsonText = jsonText.substring("```json".length(), jsonText.length() - "```".length()).trim();
					}
					else if (jsonText.startsWith("```") && jsonText.endsWith("```"))
					{
						jsonText = jsonText.substring("```".length(), jsonText.length() - "```".length()).trim();
					}
					try
					{
						final ObjectMapper mapper = new ObjectMapper();
						responseList = mapper.readValue(jsonText, ArrayList.class);
					}
					catch (final JsonProcessingException ex)
					{
						LOG.error("Exception during JSON processing of LLM response: {}", ex.getMessage(), ex);
					}
				}
				else
				{
					LOG.warn("LLM response body or its content/parts were empty or null. Response: {}", responseBody);
				}

			}
			catch (final Exception ex)
			{
				LOG.error("Exception happened during call to LLM service: {}", ex.getMessage(), ex);
			}

		}
		return responseList;
	}

	public void setOrgLifecareRestTemplateFactory(final OrgLifecareRestTemplateFactory orgLifecareRestTemplateFactory)
	{
		this.orgLifecareRestTemplateFactory = orgLifecareRestTemplateFactory;
	}

	public void setConfigurationService(final ConfigurationService configurationService)
	{
		this.configurationService = configurationService;
	}


}
