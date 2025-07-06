/*
 * Copyright (c) 2020 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderocc.controllers;

import de.hybris.platform.commercewebservicescommons.dto.prescription.OrgPrescriptionDecoderWsDTO;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgPrescriptionDecoderDocumentData;
import de.hybris.platform.orgprescriptiondecoderservice.data.OrgPrescriptionDecoderRequestData;
import de.hybris.platform.orgprescriptiondecoderservice.service.OrgPrescriptionDecoderIntegrationService;
import de.hybris.platform.webservicescommons.swagger.ApiBaseSiteIdParam;

import java.util.ArrayList;
import java.util.List;

import javax.annotation.Resource;

import org.apache.commons.codec.binary.Base64;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.multipart.MultipartFile;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;


@Controller
@Tag(name = "PrescriptionDecoder")
@RequestMapping(value = "/{baseSiteId}/prescription")
public class OrgprescriptiondecoderoccController
{
	@Resource
	private OrgPrescriptionDecoderIntegrationService orgDecoderIntegrationService;

	@PostMapping(value = "/decode")
	@ResponseBody
	@Operation(operationId = "decode prescription", summary = "decode prescription", description = "decode prescription")
	@ApiBaseSiteIdParam
	public String fetchMardownString(@RequestBody(required = true)
	final OrgPrescriptionDecoderWsDTO dto)
	{
		final OrgPrescriptionDecoderRequestData requestData = new OrgPrescriptionDecoderRequestData();
		requestData.setModel("mistral-ocr-latest");
		requestData.setInclude_image_base64(true);
		final OrgPrescriptionDecoderDocumentData sourceDoc = new OrgPrescriptionDecoderDocumentData();
		sourceDoc.setType("image_url");
		sourceDoc.setImage_url(dto.getUrl());
		requestData.setDocument(sourceDoc);
		return orgDecoderIntegrationService.getDecodedMarkDownData(requestData).replaceAll("(?m)^[ \t]*\r?\n", "")
				.replaceAll("\\r?\\n", " ").trim();
	}


	@RequestMapping(value = "/uploadPrescription", method = RequestMethod.POST)
	@ResponseBody
	public List<String> convertFileToBase64(@RequestParam("file")
	final MultipartFile uploadedFile)
	{
		String base64URL = StringUtils.EMPTY;
		List<String> decodedMedicineList = new ArrayList<>();
		if (uploadedFile == null || uploadedFile.isEmpty())
		{
			System.out.println("Attempted to convert a null or empty MultipartFile to Base64. Returning null.");
		}
		try
		{
			String imgUrlType = StringUtils.EMPTY;
			if (uploadedFile.getOriginalFilename().contains("png"))
			{
				imgUrlType = "data:image/png;base64,";
			}
			else if (uploadedFile.getOriginalFilename().contains("jpg"))
			{
				imgUrlType = "data:image/jpg;base64,";
			}
			else if (uploadedFile.getOriginalFilename().contains("pdf"))
			{
				imgUrlType = "data:application/pdf;base64,";
			}
			final byte[] fileContent = uploadedFile.getBytes();
			base64URL = imgUrlType.concat(Base64.encodeBase64String(fileContent));
			final OrgPrescriptionDecoderRequestData requestData = new OrgPrescriptionDecoderRequestData();
			requestData.setModel("mistral-ocr-latest");
			requestData.setInclude_image_base64(true);
			final OrgPrescriptionDecoderDocumentData sourceDoc = new OrgPrescriptionDecoderDocumentData();
			sourceDoc.setType("image_url");
			sourceDoc.setImage_url(base64URL);
			requestData.setDocument(sourceDoc);
			System.out.println("##################testing...");
			decodedMedicineList = orgDecoderIntegrationService.getDecodedMedicineList(requestData);
		}
		catch (final Exception ex)
		{
			ex.printStackTrace();
		}
		return decodedMedicineList;
	}
}
